"""Evaluation runner.

Scores an agent over a split, writes the run, and builds a leaderboard.
Weave is optional: if it cannot be imported or initialised, the run still
succeeds and weave_url stays empty.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
import os
import random
import shutil
import socket
import subprocess
import sys
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dh.config as dh_config
from dh.baselines import matched_chance
from dh.dets import frames_from_dets
from dh.models import ClipResult, Run, clip_meta_from_clip
from dh.score import PATTERN_VERSION, SCORER_VERSION, aggregate, score_clip

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO_ROOT / "contracts" / "examples"
_BST = timezone(timedelta(hours=1))
DVSA_REFERENCE_PCT = 0.587


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_path(data_dir: Path, name: str) -> Path:
    candidate = data_dir / name
    if candidate.is_file():
        return candidate
    fallback = _EXAMPLES / name
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(name)


def _load_clips(data_dir: Path) -> list[dict]:
    return _read_json(_load_path(data_dir, "clips.json"))


def _load_hazards(data_dir: Path) -> list[dict]:
    return _read_json(_load_path(data_dir, "hazards.json"))


def _load_testset(data_dir: Path, testset_id: str) -> dict | None:
    for base in (data_dir, _EXAMPLES):
        path = base / f"{testset_id}.json"
        if path.is_file():
            return _read_json(path)
    return None


def _hazards_for_clip(hazards: list[dict], clip_id: str) -> list[dict]:
    return [h for h in hazards if h.get("clip_id") == clip_id]


def _make_agent(agent: str, agent_config: dict | None):
    cfg = {
        k: v
        for k, v in (agent_config or {}).items()
        if k not in {"split", "testset_id"}
    }
    if agent == "yolo_risk":
        from dh.agents.yolo_risk import YoloRisk

        return YoloRisk(cfg) if cfg else YoloRisk()
    if agent == "yolo_naive":
        from dh.agents.yolo_naive import YoloNaive

        return YoloNaive()
    if agent == "yolo_cosmos_gate":
        from dh.agents.yolo_cosmos import YoloCosmosGate

        return YoloCosmosGate(cfg) if cfg else YoloCosmosGate()
    if agent == "yolo_cosmos_async":
        from dh.agents.yolo_cosmos import YoloCosmosAsync

        return YoloCosmosAsync(cfg) if cfg else YoloCosmosAsync()
    raise ValueError(f"unknown agent: {agent}")


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _normalise_click(click) -> dict:
    if isinstance(click, dict):
        return {
            "t": float(click["t"]),
            "t_trigger": float(click.get("t_trigger", click["t"])),
            "latency_s": float(click.get("latency_s", 0.0)),
            "reason": click.get("reason"),
        }
    return {
        "t": float(click.t),
        "t_trigger": float(click.t_trigger if click.t_trigger is not None else click.t),
        "latency_s": float(click.latency_s if click.latency_s is not None else 0.0),
        "reason": click.reason,
    }


def _normalise_call(call) -> dict:
    if isinstance(call, dict):
        if "kind" in call and "t_sent" in call:
            return call
        verdict = call.get("verdict")
        if verdict not in {"HAZARD", "NO_HAZARD", "ERROR", None}:
            verdict = None
        return {
            "kind": call.get("kind", "cosmos"),
            "t_sent": float(call.get("t_sent", call.get("t", 0.0))),
            "latency_s": float(call.get("latency_s", 0.0)),
            "blocking": bool(call.get("blocking", False)),
            "grid_t": call.get("grid_t", call.get("t")),
            "verdict": verdict,
        }
    data = call.model_dump() if hasattr(call, "model_dump") else dict(call)
    return data


def _sit_result_fields(sit_result) -> tuple[list, list, list]:
    if isinstance(sit_result, dict):
        return (
            sit_result.get("clicks") or [],
            sit_result.get("calls") or [],
            sit_result.get("risk_curve") or [],
        )
    return sit_result.clicks, sit_result.calls, sit_result.risk_curve


def _nearest_rank(sorted_values: list[float], proportion: float) -> float:
    """Nearest-rank percentile.

    The index is round((n - 1) * proportion), clamped to the sample.
    proportion 0.05 and 0.95 are the ends of the 90% interval.
    """
    count = len(sorted_values)
    if count == 0:
        return 0.0
    index = round((count - 1) * proportion)
    if index < 0:
        index = 0
    if index >= count:
        index = count - 1
    return float(sorted_values[index])


def bootstrap_interval(
    clip_scores: list[float],
    clip_max: list[float],
    n: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """90% interval (5th, 95th percentile) of sum(scores)/sum(max).

    Clips are resampled with replacement using random.Random(seed).
    An empty input returns (0.0, 0.0). A draw whose total max is 0
    contributes 0. The percentile index is round((n - 1) * p).
    """
    if n <= 0 or not clip_scores or not clip_max:
        return (0.0, 0.0)
    length = min(len(clip_scores), len(clip_max))
    if length == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(n):
        score_sum = 0.0
        max_sum = 0.0
        for _pick in range(length):
            index = rng.randrange(length)
            score_sum += float(clip_scores[index])
            max_sum += float(clip_max[index])
        if max_sum == 0:
            draws.append(0.0)
        else:
            draws.append(score_sum / max_sum)
    draws.sort()
    return (_nearest_rank(draws, 0.05), _nearest_rank(draws, 0.95))


def paired_interval(
    scores_a,
    scores_b,
    clip_max,
    n: int = 1000,
    seed: int = 0,
) -> tuple[float, float]:
    """90% interval of pct(A) - pct(B) on shared resampled indexes."""
    if n <= 0 or not scores_a or not scores_b or not clip_max:
        return (0.0, 0.0)
    length = min(len(scores_a), len(scores_b), len(clip_max))
    if length == 0:
        return (0.0, 0.0)
    rng = random.Random(seed)
    draws: list[float] = []
    for _ in range(n):
        sum_a = 0.0
        sum_b = 0.0
        max_sum = 0.0
        for _pick in range(length):
            index = rng.randrange(length)
            sum_a += float(scores_a[index])
            sum_b += float(scores_b[index])
            max_sum += float(clip_max[index])
        if max_sum == 0:
            draws.append(0.0)
        else:
            draws.append((sum_a - sum_b) / max_sum)
    draws.sort()
    return (_nearest_rank(draws, 0.05), _nearest_rank(draws, 0.95))


def label_sensitivity(
    click_times_by_clip,
    hazards_by_clip,
    durations,
    labellers: tuple[str, str] = ("riyu", "fmd"),
) -> dict:
    """Rescore with each labeller's window.

    hazard['labellers'][name] is [start, end]. A missing labeller is
    skipped, not invented. The result keeps a labeller only when at least
    one window was present. Scoring uses dh.score.score_clip.
    """
    totals = {name: {"score": 0, "max": 0, "seen": False} for name in labellers}
    for clicks, hazards, duration in zip(click_times_by_clip, hazards_by_clip, durations):
        for name in labellers:
            rewritten = []
            for hazard in hazards:
                windows = hazard.get("labellers") or {}
                window = windows.get(name)
                if not isinstance(window, (list, tuple)) or len(window) < 2:
                    continue
                copied = dict(hazard)
                copied["window_start"] = float(window[0])
                copied["window_end"] = float(window[1])
                rewritten.append(copied)
            if not rewritten:
                continue
            totals[name]["seen"] = True
            scored = score_clip(list(clicks), rewritten, float(duration))
            totals[name]["score"] += int(scored["clip_score"])
            totals[name]["max"] += 5 * len(rewritten)
    result = {}
    for name in labellers:
        if not totals[name]["seen"]:
            continue
        score = int(totals[name]["score"])
        maximum = int(totals[name]["max"])
        pct = score / maximum if maximum else 0.0
        result[name] = {"score": score, "max": maximum, "pct": pct}
    return result


def latency_modes() -> list[str]:
    return ["zero", "fixed:0.5", "fixed:1", "fixed:2", "fixed:4"]


def _quiet_loggers(names: tuple[str, ...]) -> list[tuple[logging.Logger, int, bool]]:
    saved = []
    for name in names:
        logger = logging.getLogger(name)
        saved.append((logger, logger.level, logger.disabled))
        logger.setLevel(logging.CRITICAL)
        logger.disabled = True
    return saved


def _restore_loggers(saved: list[tuple[logging.Logger, int, bool]]) -> None:
    for logger, level, disabled in saved:
        logger.setLevel(level)
        logger.disabled = disabled


def _weave_model_name(agent: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in agent)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "agent_" + cleaned
    return cleaned or "agent"


def _record_weave(run_doc: dict, clip_rows: list[dict], interval: tuple[float, float]) -> str:
    """Log one prediction per clip. Any failure leaves the URL empty.

    Exception text is discarded so an API key cannot be stored.
    """
    try:
        team = dh_config.WANDB_TEAM
        project = dh_config.WANDB_PROJECT
    except Exception:
        return ""
    if not isinstance(team, str) or not isinstance(project, str):
        return ""
    if not team or not project:
        return ""
    try:
        import weave
    except Exception:
        return ""
    logger_cls = getattr(weave, "EvaluationLogger", None)
    if logger_cls is None:
        return ""

    sink = io.StringIO()
    saved_logs = _quiet_loggers(("weave", "wandb"))
    previous_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    previous_timeout = socket.getdefaulttimeout()
    retry_attempts = os.environ.get("WEAVE_RETRY_MAX_ATTEMPTS")
    retry_interval = os.environ.get("WEAVE_RETRY_MAX_INTERVAL")
    introduced_attempts = False
    introduced_interval = False
    if retry_attempts is None:
        os.environ["WEAVE_RETRY_MAX_ATTEMPTS"] = "1"
        introduced_attempts = True
    if retry_interval is None:
        os.environ["WEAVE_RETRY_MAX_INTERVAL"] = "1"
        introduced_interval = True
    socket.setdefaulttimeout(2.0)
    evaluation = None
    url = ""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                weave.init(f"{team}/{project}")
                testset_id = str(run_doc.get("testset_id") or "")
                eval_name = "dh-test-v2" if "test" in testset_id else "dh-dev-sweep"
                evaluation = logger_cls(
                    name=eval_name,
                    model=_weave_model_name(str(run_doc.get("agent") or "agent")),
                    dataset=testset_id or "clips",
                    eval_attributes={
                        "git_sha": str(run_doc.get("git_sha") or ""),
                        "testset_sha256": str(run_doc.get("testset_sha256") or ""),
                        "pattern_version": str(run_doc.get("pattern_version") or ""),
                        "latency_mode": str(run_doc.get("latency_mode") or ""),
                    },
                )
                totals = run_doc.get("totals") or {}
                for row in clip_rows:
                    prediction = evaluation.log_prediction(
                        inputs={"clip_id": row["clip_id"]},
                        output=row["clip_score"],
                    )
                    _log_clip_scores(prediction, row)
                ui = getattr(evaluation, "ui_url", None)
                if isinstance(ui, str):
                    url = ui
                if hasattr(evaluation, "log_summary"):
                    evaluation.log_summary(
                        {
                            "pct": totals.get("pct"),
                            "lift_vs_chance": totals.get("lift_vs_chance"),
                            "ci90_low": interval[0],
                            "ci90_high": interval[1],
                        }
                    )
    except Exception:
        url = ""
    finally:
        if evaluation is not None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                        evaluation.finish()
            except Exception:
                pass
        socket.setdefaulttimeout(previous_timeout)
        logging.disable(previous_disable)
        if introduced_attempts:
            os.environ.pop("WEAVE_RETRY_MAX_ATTEMPTS", None)
        if introduced_interval:
            os.environ.pop("WEAVE_RETRY_MAX_INTERVAL", None)
        _restore_loggers(saved_logs)
        # Drop anything Weave printed. It is not stored.
        sink.close()
    if not isinstance(url, str):
        return ""
    return url


def _log_clip_scores(prediction, row: dict) -> None:
    if prediction is None or not hasattr(prediction, "log_score"):
        return
    pattern = row.get("pattern") or {}
    points = row.get("hazard_points") or {}
    hit = any(int(value) >= 1 for value in points.values())
    latencies = []
    for call in row.get("calls") or []:
        if isinstance(call, dict) and call.get("latency_s") is not None:
            latencies.append(float(call["latency_s"]))
    latency_s = sum(latencies) / len(latencies) if latencies else 0.0
    reactions = []
    for hazard in row.get("hazards") or []:
        first = hazard.get("first_click")
        window = hazard.get("window") or []
        if first is not None and len(window) >= 1:
            reactions.append(float(first) - float(window[0]))
    reaction_s = sorted(reactions)[len(reactions) // 2] if reactions else 0.0
    scores = {
        "points": float(row.get("clip_score") or 0),
        "hit": bool(hit),
        "reaction_s": float(reaction_s),
        "pattern_flag": bool(pattern.get("flag")),
        "latency_s": float(latency_s),
    }
    for name, value in scores.items():
        try:
            prediction.log_score(name, value)
        except Exception:
            return


def _dev_only(clips: list[dict]) -> list[dict]:
    chosen = [clip for clip in clips if clip.get("split") == "dev"]
    for clip in chosen:
        assert clip.get("split") == "dev", "tune_dev refuses split test"
    return chosen


def start_run(
    agent: str,
    config: dict | None = None,
    testset_id: str = "testset_v0",
    latency_mode: str = "zero",
    split: str | None = None,
    data_dir: str | Path | None = None,
) -> str:
    """Write run.json and clips.jsonl under data_dir/runs/<run_id>/."""
    from dh.models import Clip
    from dh.replay import sit_clip

    root = Path(data_dir) if data_dir is not None else Path(dh_config.DATA_DIR)
    agent_config = config if config is not None else {}
    if split is None:
        split = agent_config.get("split")
    if split is None:
        split = "dev"

    all_clips = _load_clips(root)
    all_hazards = _load_hazards(root)
    testset = _load_testset(root, testset_id)

    if testset:
        clip_ids = set(testset.get("clips") or [])
        clips = [c for c in all_clips if c.get("clip_id") in clip_ids]
        testset_sha256 = testset.get("sha256", "unfrozen")
    else:
        clips = [c for c in all_clips if c.get("split") == split]
        testset_sha256 = "unfrozen"

    started = datetime.now(_BST).replace(microsecond=0)
    run_id = f"r_{agent}_{started.strftime('%Y%m%dT%H%M%S')}"
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    agent_obj = _make_agent(agent, agent_config)
    clip_rows: list[dict] = []
    aggregate_rows: list[dict] = []
    chance_clips: list[dict] = []
    clicks_per_clip: list[int] = []

    for clip in clips:
        clip_id = clip["clip_id"]
        hazards = _hazards_for_clip(all_hazards, clip_id)
        chance_clips.append(
            {
                "duration_s": clip["duration_s"],
                "hazards": hazards,
            }
        )
        det_path = root / "det" / f"{clip_id}.jsonl"
        if det_path.is_file():
            dets = []
            for line in det_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if isinstance(obj, dict) and obj.get("_meta"):
                    continue
                dets.append(obj)
            frames = frames_from_dets(dets)
        else:
            frames = [(0.0, "", [])]

        meta = clip_meta_from_clip(Clip.model_validate(clip))
        verifier = None
        if agent in {"yolo_cosmos_gate", "yolo_cosmos_async"}:
            from dh.grid import GridVerifier

            grid_path = root / "grid" / "cosmos_verify_v2" / f"{clip_id}.jsonl"
            if grid_path.is_file():
                verifier = GridVerifier(path=grid_path)
        sit_result = sit_clip(
            agent_obj,
            meta,
            frames,
            verifier=verifier,
            latency_mode=latency_mode,
        )
        raw_clicks, raw_calls, risk_curve = _sit_result_fields(sit_result)
        clicks = [_normalise_click(c) for c in raw_clicks]
        calls = [_normalise_call(c) for c in raw_calls]
        click_times = [c["t"] for c in clicks]
        clicks_per_clip.append(len(clicks))

        scored = score_clip(click_times, hazards, float(clip["duration_s"]))
        curve = (
            [[float(a), float(b)] for a, b in risk_curve]
            if risk_curve
            else []
        )

        clip_result = {
            "run_id": run_id,
            "clip_id": clip_id,
            "clicks": clicks,
            "calls": calls,
            "pattern": scored["pattern"],
            "hazard_points": scored["hazard_points"],
            "clip_score": scored["clip_score"],
            "risk_curve": curve,
            "explanation": None,
        }
        ClipResult.model_validate(clip_result)
        clip_rows.append(clip_result)

        aggregate_rows.append(
            {
                **scored,
                "clicks": clicks,
                "calls": calls,
            }
        )

    totals = aggregate(aggregate_rows)
    totals["lift_vs_chance"] = totals["pct"] - matched_chance(
        clicks_per_clip, chance_clips, n=dh_config.random_draws_matched, seed=0
    )
    interval = bootstrap_interval(
        [float(row["clip_score"]) for row in clip_rows],
        [float(5 * len(row.get("hazard_points") or {})) for row in clip_rows],
    )

    run_doc = {
        "run_id": run_id,
        "agent": agent,
        "agent_config": agent_config,
        "testset_id": testset_id,
        "testset_sha256": testset_sha256,
        "scorer_version": SCORER_VERSION,
        "pattern_version": PATTERN_VERSION,
        "latency_mode": latency_mode,
        "git_sha": _git_sha(),
        "mode": "fast",
        "started_at": started.isoformat(),
        "weave_url": "",
        "totals": totals,
    }
    try:
        weave_url = _record_weave(run_doc, clip_rows, interval)
    except Exception:
        weave_url = ""
    run_doc["weave_url"] = weave_url if isinstance(weave_url, str) else ""
    Run.model_validate(run_doc)

    (run_dir / "run.json").write_text(
        json.dumps(run_doc, indent=2) + "\n",
        encoding="utf-8",
    )
    with (run_dir / "clips.jsonl").open("w", encoding="utf-8") as handle:
        for row in clip_rows:
            handle.write(json.dumps(row) + "\n")

    return run_id


def _as_float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _clip_bootstrap(run_dir: Path) -> tuple[float, float]:
    scores: list[float] = []
    maxima: list[float] = []
    path = run_dir / "clips.jsonl"
    if not path.is_file():
        return (0.0, 0.0)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            continue
        scores.append(float(row.get("clip_score") or 0))
        maxima.append(float(5 * len(row.get("hazard_points") or {})))
    return bootstrap_interval(scores, maxima)


def _agent_row(name: str, doc: dict, run_dir: Path) -> tuple[dict, int]:
    totals = doc.get("totals") or {}
    score = int(totals.get("score") or 0)
    maximum = int(totals.get("max") or 0)
    pct = _as_float(totals.get("pct"), score / maximum if maximum else 0.0)
    lo, hi = _clip_bootstrap(run_dir)
    if "lift_vs_chance" in totals and totals.get("lift_vs_chance") is not None:
        lift = float(totals["lift_vs_chance"])
    else:
        lift = 0.0
    weave_url = doc.get("weave_url")
    row = {
        "name": name,
        "kind": "agent",
        "score": score,
        "pct": pct,
        "ci90": [lo, hi],
        "lift_vs_chance": lift,
        "hit_rate": _as_float(totals.get("hit_rate")),
        "pattern_rate": _as_float(totals.get("pattern_rate")),
        "reaction_s": _as_float(totals.get("median_reaction_s")),
        "latency_s": _as_float(totals.get("mean_latency_s")),
        "weave_url": weave_url if isinstance(weave_url, str) else "",
    }
    return row, maximum


def _latest_runs(root: Path, testset_id: str, agents: list[str] | None) -> dict[str, tuple]:
    latest: dict[str, tuple] = {}
    runs_dir = root / "runs"
    if not runs_dir.is_dir():
        return latest
    allowed = None if agents is None else set(agents)
    for run_json in runs_dir.glob("*/run.json"):
        doc = _read_json(run_json)
        if not isinstance(doc, dict) or doc.get("testset_id") != testset_id:
            continue
        name = doc.get("agent")
        if not isinstance(name, str) or not name:
            continue
        if allowed is not None and name not in allowed:
            continue
        stamp = str(doc.get("started_at") or "")
        key = (stamp, str(doc.get("run_id") or ""))
        previous = latest.get(name)
        if previous is None or key >= previous[0]:
            latest[name] = (key, doc, run_json.parent)
    return latest


def _human_rows(root: Path) -> tuple[list[dict], int]:
    path = root / "humans.jsonl"
    if not path.is_file():
        return [], 0
    sessions: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        item = json.loads(line)
        if isinstance(item, dict) and item.get("blind") is True:
            sessions.append(item)
    if not sessions:
        return [], 0

    clips = {clip.get("clip_id"): clip for clip in _load_clips(root)}
    hazards = _load_hazards(root)
    by_name: dict[str, list[dict]] = {}
    for session in sessions:
        name = session.get("name")
        if not isinstance(name, str) or not name:
            continue
        by_name.setdefault(name, []).append(session)

    rows = []
    board_max = 0
    for name in sorted(by_name):
        scores: list[float] = []
        maxima: list[float] = []
        aggregate_rows: list[dict] = []
        for session in by_name[name]:
            clip = clips.get(session.get("clip_id"))
            if not isinstance(clip, dict):
                continue
            clip_hazards = _hazards_for_clip(hazards, session["clip_id"])
            clicks = [float(t) for t in (session.get("clicks") or [])]
            scored = score_clip(clicks, clip_hazards, float(clip["duration_s"]))
            aggregate_rows.append({**scored, "clicks": clicks, "calls": []})
            scores.append(float(scored["clip_score"]))
            maxima.append(float(5 * len(scored.get("hazard_points") or {})))
        if not aggregate_rows:
            continue
        totals = aggregate(aggregate_rows)
        maximum = int(totals.get("max") or 0)
        board_max = max(board_max, maximum)
        pct = _as_float(totals.get("pct"))
        if len(scores) == 1:
            ci90 = [pct, pct]
        else:
            lo, hi = bootstrap_interval(scores, maxima)
            ci90 = [lo, hi]
        rows.append(
            {
                "name": name,
                "kind": "human",
                "score": int(totals.get("score") or 0),
                "pct": pct,
                "ci90": ci90,
                "lift_vs_chance": 0.0,
                "hit_rate": _as_float(totals.get("hit_rate")),
                "pattern_rate": _as_float(totals.get("pattern_rate")),
                "reaction_s": _as_float(totals.get("median_reaction_s")),
                "latency_s": 0.0,
                "weave_url": "",
            }
        )
    return rows, board_max


def build_leaderboard(
    testset_id: str,
    data_dir=None,
    agents: list[str] | None = None,
) -> dict:
    """Write leaderboard.json for one test set.

    Agent rows come from data/runs/*/run.json with this testset_id, latest
    run per agent. ci90 is a clip bootstrap. lift_vs_chance comes from the
    run totals when present, otherwise 0. Blind humans are added only when
    humans.jsonl exists. A missing file adds no human rows.
    """
    root = Path(data_dir) if data_dir is not None else Path(dh_config.DATA_DIR)
    latest = _latest_runs(root, testset_id, agents)
    if agents is None:
        names = sorted(
            latest,
            key=lambda name: (
                -_as_float((latest[name][1].get("totals") or {}).get("pct")),
                name,
            ),
        )
    else:
        names = [name for name in agents if name in latest]

    rows = []
    board_max = 0
    for name in names:
        _key, doc, run_dir = latest[name]
        row, maximum = _agent_row(name, doc, run_dir)
        rows.append(row)
        board_max = max(board_max, maximum)

    human_rows, human_max = _human_rows(root)
    if not rows:
        board_max = max(board_max, human_max)
    rows.extend(human_rows)

    if not latest and not human_rows:
        board_max = 0
        rows = []

    payload = {
        "testset_id": testset_id,
        "max": board_max,
        "dvsa_reference_pct": DVSA_REFERENCE_PCT,
        "rows": rows,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "leaderboard.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    return payload


def _run_score(stage: Path, run_id: str) -> float | None:
    path = stage / "runs" / run_id / "run.json"
    if not path.is_file():
        return None
    totals = _read_json(path).get("totals") or {}
    score = totals.get("score")
    if score is None:
        return None
    return float(score)


def tune_dev(data_dir=None, split: str = "dev") -> dict:
    """SPEC 12.6. DEV ONLY.

    Refuses a request to include the test split. Only clips with split
    "dev" are staged, and every staged clip is asserted to be dev.
    YoloRisk reads dh.config and ignores a constructor config, so the
    sweep is the published default run rather than a grid.
    """
    if split != "dev":
        raise ValueError("tune_dev refuses split test")

    root = Path(data_dir) if data_dir is not None else Path(dh_config.DATA_DIR)
    dev_clips = _dev_only(_load_clips(root))
    stage = root / "_tune_dev"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    try:
        (stage / "clips.json").write_text(
            json.dumps(dev_clips, indent=2) + "\n",
            encoding="utf-8",
        )
        hazards_path = root / "hazards.json"
        if hazards_path.is_file():
            dev_ids = {clip.get("clip_id") for clip in dev_clips}
            kept = [
                hazard
                for hazard in _read_json(hazards_path)
                if hazard.get("clip_id") in dev_ids
            ]
            (stage / "hazards.json").write_text(
                json.dumps(kept, indent=2) + "\n",
                encoding="utf-8",
            )
        det_dir = stage / "det"
        for clip in dev_clips:
            clip_id = clip.get("clip_id")
            source = root / "det" / f"{clip_id}.jsonl"
            if clip_id and source.is_file():
                det_dir.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, det_dir / source.name)
        # A testset id that is not a file, so start_run keeps the dev filter.
        # Ties keep the published default so a flat dev set does not move it.
        best = {"theta_up": 0.6, "ema_weight": 0.4}
        best_score: float | None = None
        for theta_up, ema_weight in (
            (0.5, 0.4),
            (0.5, 0.7),
            (0.6, 0.4),
            (0.6, 0.7),
            (0.7, 0.4),
            (0.7, 0.7),
        ):
            run_id = start_run(
                "yolo_risk",
                {"split": "dev", "theta_up": theta_up, "ema_weight": ema_weight},
                testset_id="dev_tune",
                latency_mode="zero",
                split="dev",
                data_dir=stage,
            )
            score = _run_score(stage, run_id)
            if score is None:
                continue
            if best_score is None or score > best_score:
                best_score = score
                best = {"theta_up": theta_up, "ema_weight": ema_weight}
            elif score == best_score and theta_up == 0.6 and ema_weight == 0.4:
                best = {"theta_up": theta_up, "ema_weight": ema_weight}
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    return {
        "split": "dev",
        "tuned_on_test": False,
        "best": best,
        "note": "dev only; ties keep the published default; no test clip was scored",
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an agent on a split.")
    parser.add_argument("--agent", default="")
    parser.add_argument("--split", default="dev")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if not args.agent:
        print("usage: python -m dh.evals --agent <name> [--split dev]", file=sys.stderr)
        return 2
    run_config = {"split": args.split}
    print(start_run(args.agent, run_config, latency_mode="zero"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
