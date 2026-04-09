from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.db.session import create_session_factory
from app.services.auth_service import ensure_bootstrap_users
from app.services.internal_scheduler import InternalScheduleRunner
from app.services.query_jobs import QueryJobManager

logger = logging.getLogger(__name__)


def _fallback_settings() -> Settings:
    runtime_root = Path(".runtime")
    runtime_root.mkdir(exist_ok=True)
    return Settings.model_validate(
        {
            "APP_ENV": "test",
            "APP_HOST": "127.0.0.1",
            "APP_PORT": 8000,
            "APP_TIMEZONE": "Asia/Seoul",
            "CONF_MIRROR_BASE_URL": "https://mirror.example.com/confluence",
            "CONF_PROD_BASE_URL": "https://prod.example.com/confluence",
            "CONF_USERNAME": "user",
            "CONF_PASSWORD": "pass",
            "CONF_VERIFY_SSL": False,
            "INTERNAL_SCHEDULER_ENABLED": True,
            "INTERNAL_SCHEDULER_POLL_SECONDS": 60,
            "DATABASE_URL": f"sqlite:///{runtime_root / 'app.db'}",
            "WIKI_ROOT": str(runtime_root / "wiki"),
            "CACHE_ROOT": str(runtime_root / "cache"),
            "LLM_BASE_URL": "http://api.net:8000/v1",
            "LLM_MODEL": "QWEN3",
            "VLM_BASE_URL": "http://api.net/vl/v1",
            "VLM_MODEL": "QWEN3-VL",
        }
    )


def create_app(settings: Settings | None = None, allow_test_fallback: bool | None = None) -> FastAPI:
    if allow_test_fallback is None:
        allow_test_fallback = "pytest" in sys.modules
    if settings is None:
        try:
            settings = get_settings()
        except ValidationError:
            if not allow_test_fallback:
                raise
            settings = _fallback_settings()

    settings.wiki_root.mkdir(parents=True, exist_ok=True)
    settings.cache_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Confluence Wiki")
    app.add_middleware(SessionMiddleware, secret_key=settings.auth_secret_key, same_site="lax")
    app.state.settings = settings
    app.state.session_factory = create_session_factory(settings.database_url)
    app.state.templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    app.state.query_jobs = QueryJobManager(settings)

    bootstrap_session = app.state.session_factory()
    try:
        ensure_bootstrap_users(bootstrap_session, settings)
        bootstrap_session.commit()
    finally:
        bootstrap_session.close()

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.mount("/wiki-static", StaticFiles(directory=str(settings.wiki_root)), name="wiki-static")
    app.include_router(router)

    if settings.internal_scheduler_enabled:
        @app.on_event("startup")
        async def _start_internal_scheduler() -> None:
            stop_event = asyncio.Event()
            runner = InternalScheduleRunner(settings, app.state.query_jobs, app.state.session_factory)
            app.state.internal_scheduler_stop = stop_event

            async def _loop() -> None:
                interval = max(5, int(settings.internal_scheduler_poll_seconds))
                while not stop_event.is_set():
                    try:
                        await runner.run_once()
                    except Exception:
                        logger.exception("internal scheduler loop failed")
                    try:
                        await asyncio.wait_for(stop_event.wait(), timeout=interval)
                    except TimeoutError:
                        continue

            app.state.internal_scheduler_task = asyncio.create_task(_loop())

        @app.on_event("shutdown")
        async def _stop_internal_scheduler() -> None:
            stop_event = getattr(app.state, "internal_scheduler_stop", None)
            task = getattr(app.state, "internal_scheduler_task", None)
            if stop_event is not None:
                stop_event.set()
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    return app


app = create_app()
