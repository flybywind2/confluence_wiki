from pathlib import Path

import pytest


@pytest.fixture()
def sample_settings_dict(tmp_path: Path) -> dict[str, object]:
    return {
        "APP_TIMEZONE": "Asia/Seoul",
        "CONF_MIRROR_BASE_URL": "https://mirror.example.com/confluence",
        "CONF_PROD_BASE_URL": "https://prod.example.com/confluence",
        "CONF_USERNAME": "user",
        "CONF_PASSWORD": "pass",
        "CONF_VERIFY_SSL": False,
        "INTERNAL_SCHEDULER_ENABLED": False,
        "DATABASE_URL": f"sqlite:///{tmp_path / 'app.db'}",
        "WIKI_ROOT": str(tmp_path / "wiki"),
        "CACHE_ROOT": str(tmp_path / "cache"),
        "LLM_BASE_URL": "http://api.net:8000/v1",
        "LLM_MODEL": "QWEN3",
        "LLM_DEP_TICKET": "credential:TICKET-",
        "LLM_SEND_SYSTEM_NAME": "test",
        "LLM_USER_ID": "ID",
        "LLM_USER_TYPE": "AD_ID",
        "VLM_BASE_URL": "http://api.net/vl/v1",
        "VLM_MODEL": "QWEN3-VL",
        "VLM_DEP_TICKET": "credential:TICKET-",
        "VLM_SEND_SYSTEM_NAME": "test",
        "VLM_USER_ID": "ID",
        "VLM_USER_TYPE": "AD_ID",
    }
