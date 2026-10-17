"""Minimal eval runner (Phase 2). Weave and leaderboard are Phase 3."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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

        return YoloNaive(cfg) if cfg else YoloNaive()
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
        return call
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
        sit_result = sit_clip(
            agent_obj,
            meta,
            frames,
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
    Run.model_validate(run_doc)

    (run_dir / "run.json").write_text(
        json.dumps(run_doc, indent=2) + "\n",
        encoding="utf-8",
    )
    with (run_dir / "clips.jsonl").open("w", encoding="utf-8") as handle:
        for row in clip_rows:
            handle.write(json.dumps(row) + "\n")

    return run_id


def build_leaderboard(testset_id: str) -> dict:
    """Phase 3."""
    raise NotImplementedError("leaderboard is phase 3")


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
