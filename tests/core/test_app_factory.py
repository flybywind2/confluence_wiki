import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.main import create_app


def test_create_app_fails_fast_without_env_outside_test_fallback(monkeypatch):
    for key in [
        "CONF_MIRROR_BASE_URL",
        "CONF_PROD_BASE_URL",
        "CONF_USERNAME",
        "CONF_PASSWORD",
        "DATABASE_URL",
        "WIKI_ROOT",
        "CACHE_ROOT",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "VLM_BASE_URL",
        "VLM_MODEL",
    ]:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValidationError):
        create_app(allow_test_fallback=False)


def test_create_app_creates_missing_sqlite_parent_dirs(tmp_path, sample_settings_dict):
    sample_settings_dict["DATABASE_URL"] = f"sqlite:///{tmp_path / 'nested' / 'db' / 'app.db'}"
    sample_settings_dict["WIKI_ROOT"] = str(tmp_path / "wiki")
    sample_settings_dict["CACHE_ROOT"] = str(tmp_path / "cache")
    settings = Settings.model_validate(sample_settings_dict)

    app = create_app(settings=settings, allow_test_fallback=False)

    assert app.title == "Confluence Wiki"
