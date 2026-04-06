from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.api.routes import router
from app.core.config import Settings, get_settings
from app.db.session import create_session_factory


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
    app.state.settings = settings
    app.state.session_factory = create_session_factory(settings.database_url)
    app.state.templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.mount("/wiki-static", StaticFiles(directory=str(settings.wiki_root)), name="wiki-static")
    app.include_router(router)
    return app


app = create_app()
