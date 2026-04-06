from app.core.config import Settings


def test_settings_load_required_confluence_and_llm_fields(sample_settings_dict):
    settings = Settings.model_validate(sample_settings_dict)

    assert settings.conf_verify_ssl is False
    assert settings.sync_rate_limit_per_minute == 10
    assert settings.app_timezone == "Asia/Seoul"
