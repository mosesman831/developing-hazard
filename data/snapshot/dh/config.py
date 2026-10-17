"""Environment and configuration defaults (SPEC sections 18.5 and 19)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_CONFIG_FILE_CACHE: dict[str, str] | None = None
_CONFIG_PATH_RESOLVED: bool = False

_CORRIDOR: dict[str, float] = {
    "bottom_x0": 0.25,
    "bottom_x1": 0.75,
    "top_x0": 0.42,
    "top_x1": 0.58,
    "top_y": 0.55,
}

_PATTERN: dict[str, Any] = {
    "version": "PATTERN_V1",
    "p1_max_clicks": 8,
    "p2_max_in_window": 4,
    "p2_window_s": 2.0,
    "p3_min_clicks": 5,
    "p3_cv_max": 0.15,
    "p4_bin_coverage": 0.7,
}

_CONFIG_FIRST_KEYS = frozenset({"USERNAME", "PASSWORD"})

_LAZY_ENV_NAMES = frozenset(
    {
        "GPU_BEARER_TOKEN",
        "COSMOS3_REASON_URL",
        "YOLO_URL",
        "COSMOS_EMBED1_URL",
        "WANDB_API_KEY",
        "WANDB_TEAM",
        "WANDB_PROJECT",
        "DH_LLM_MODEL",
        "DH_VLM_MODEL",
        "INGRESS_URL",
    }
)

_PUBLIC_ATTRS = frozenset(
    {
        "DATA_DIR",
        "MODE",
        "fps_sample",
        "det_conf_min",
        "min_box_h",
        "corridor",
        "theta_up",
        "theta_down",
        "ema_weight",
        "theta_trig",
        "max_clicks",
        "min_click_gap_s",
        "max_clicks_async",
        "min_click_gap_async_s",
        "max_verify_calls",
        "grid_step_s",
        "grid_risk_min",
        "verify_context_s",
        "verify_in_flight",
        "llm_period_s",
        "pattern_version",
        "pattern",
        "window_len_min_s",
        "window_len_max_s",
        "agree_tol_start_s",
        "agree_tol_end_s",
        "bootstrap_n",
        "random_draws_per_k",
        "random_draws_matched",
        "pod_budget_kb",
        "USERNAME",
        "PASSWORD",
    }
    | _LAZY_ENV_NAMES
)


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _find_config_path() -> Path | None:
    explicit = os.environ.get("DH_CONFIG")
    if explicit:
        path = Path(explicit)
        if path.is_file():
            return path
        return None

    config_dir = Path("/config")
    if not config_dir.is_dir():
        return None
    matches = sorted(config_dir.glob("*.config"))
    if len(matches) == 1:
        return matches[0]
    return None


def _parse_config_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, raw_value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        data[key] = _strip_quotes(raw_value)
    return data


def _config_file_data() -> dict[str, str]:
    global _CONFIG_FILE_CACHE, _CONFIG_PATH_RESOLVED
    if not _CONFIG_PATH_RESOLVED:
        path = _find_config_path()
        _CONFIG_FILE_CACHE = _parse_config_file(path) if path else {}
        _CONFIG_PATH_RESOLVED = True
    return _CONFIG_FILE_CACHE or {}


def _from_config(name: str) -> str | None:
    return _config_file_data().get(name)


def _from_os_environ(name: str) -> str | None:
    return os.environ.get(name)


def lookup(name: str, default: str | None = None) -> str | None:
    """Resolve a setting: config-first for USERNAME/PASSWORD, else env then config."""
    if name in _CONFIG_FIRST_KEYS:
        cfg = _from_config(name)
        if cfg is not None:
            return cfg
        env_val = _from_os_environ(name)
        if env_val is not None:
            return env_val
        return default

    env_val = _from_os_environ(name)
    if env_val is not None:
        return env_val
    cfg = _from_config(name)
    if cfg is not None:
        return cfg
    return default


def env(name: str, default: str | None = None) -> str | None:
    """Look up a named setting (team config and environment)."""
    return lookup(name, default)


def _fps_sample() -> int:
    raw = lookup("DH_FPS_SAMPLE")
    if raw is None:
        return 5
    return int(raw)


def __getattr__(name: str) -> Any:
    if name == "DATA_DIR":
        return lookup("DH_DATA_DIR", "data")
    if name == "MODE":
        return lookup("DH_MODE", "dev")
    if name == "fps_sample":
        return _fps_sample()
    if name == "det_conf_min":
        return 0.35
    if name == "min_box_h":
        return 0.035
    if name == "corridor":
        return _CORRIDOR
    if name == "theta_up":
        return 0.6
    if name == "theta_down":
        return 0.4
    if name == "ema_weight":
        return 0.4
    if name == "theta_trig":
        return 0.45
    if name == "max_clicks":
        return 3
    if name == "min_click_gap_s":
        return 1.5
    if name == "max_clicks_async":
        return 4
    if name == "min_click_gap_async_s":
        return 1.2
    if name == "max_verify_calls":
        return 4
    if name == "grid_step_s":
        return 0.5
    if name == "grid_risk_min":
        return 0.3
    if name == "verify_context_s":
        return 2.0
    if name == "verify_in_flight":
        return 2
    if name == "llm_period_s":
        return 0.5
    if name == "pattern_version":
        return "PATTERN_V1"
    if name == "pattern":
        return _PATTERN
    if name == "window_len_min_s":
        return 1.0
    if name == "window_len_max_s":
        return 7.0
    if name == "agree_tol_start_s":
        return 0.6
    if name == "agree_tol_end_s":
        return 0.8
    if name == "bootstrap_n":
        return 1000
    if name == "random_draws_per_k":
        return 200
    if name == "random_draws_matched":
        return 1000
    if name == "pod_budget_kb":
        return 1024
    if name in _LAZY_ENV_NAMES or name in _CONFIG_FIRST_KEYS:
        return lookup(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | _PUBLIC_ATTRS | {"env", "lookup"})
