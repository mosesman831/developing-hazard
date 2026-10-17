"""FastAPI app for the dev server and the demo pod.

API routes are registered before the static mount so ``/health``, ``/api``
and ``/video`` are not shadowed by files in ``web/``.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from starlette.staticfiles import StaticFiles

from dh.api._stubs import current_mode
from dh.api.clips import router as clips_router
from dh.api.health import router as health_router
from dh.api.human import router as human_router
from dh.api.leaderboard import router as leaderboard_router
from dh.api.runs import router as runs_router
from dh.api.video import router as video_router

_ROOT = Path(__file__).resolve().parents[1]
_WEB_DIR = _ROOT / "web"
_SPATIAL_DIR = _ROOT / "spatial"


def _root_health() -> dict:
    return {"ok": True}


def create_app() -> FastAPI:
    """Build an app, reading DH_MODE at call time.

    Tests monkeypatch the environment before this runs. ``current_mode``
    uses ``os.environ.get("DH_MODE", "dev")`` and, when that variable is
    unset, ``dh.config.MODE`` if the import works. The labels router is
    mounted only in dev, and only if it imports.
    """
    mode = os.environ.get("DH_MODE", "dev")
    if "DH_MODE" not in os.environ:
        mode = current_mode()

    application = FastAPI()
    application.add_api_route("/health", _root_health, methods=["GET"])
    application.include_router(health_router)
    application.include_router(clips_router)
    application.include_router(video_router)
    application.include_router(runs_router)
    application.include_router(human_router)
    application.include_router(leaderboard_router)

    if mode == "dev":
        try:
            from dh.api.labels import router as labels_router
        except ImportError:
            labels_router = None
        if labels_router is not None:
            application.include_router(labels_router)

    if _SPATIAL_DIR.is_dir():
        application.mount(
            "/spatial",
            StaticFiles(directory=str(_SPATIAL_DIR), html=True),
            name="spatial",
        )
    if _WEB_DIR.is_dir():
        application.mount(
            "/",
            StaticFiles(directory=str(_WEB_DIR), html=True),
            name="web",
        )
    return application


app = create_app()


def main() -> None:
    host = "0.0.0.0"
    port = int(os.environ.get("PORT") or os.environ.get("DH_PORT") or 8000)
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("uvicorn is not installed")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
