from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    app_env: str = Field(default="local", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    app_timezone: str = Field(default="Asia/Seoul", alias="APP_TIMEZONE")
    auth_secret_key: str = Field(default="dev-secret-key", alias="AUTH_SECRET_KEY")
    auth_bootstrap_admin_username: str = Field(default="admin", alias="AUTH_BOOTSTRAP_ADMIN_USERNAME")
    auth_bootstrap_admin_password: str = Field(default="admin-pass", alias="AUTH_BOOTSTRAP_ADMIN_PASSWORD")
    auth_bootstrap_editor_username: str = Field(default="editor", alias="AUTH_BOOTSTRAP_EDITOR_USERNAME")
    auth_bootstrap_editor_password: str = Field(default="editor-pass", alias="AUTH_BOOTSTRAP_EDITOR_PASSWORD")
    auth_bootstrap_viewer_username: str = Field(default="viewer", alias="AUTH_BOOTSTRAP_VIEWER_USERNAME")
    auth_bootstrap_viewer_password: str = Field(default="viewer-pass", alias="AUTH_BOOTSTRAP_VIEWER_PASSWORD")

    conf_mirror_base_url: str = Field(alias="CONF_MIRROR_BASE_URL")
    conf_prod_base_url: str = Field(alias="CONF_PROD_BASE_URL")
    conf_username: str = Field(alias="CONF_USERNAME")
    conf_password: str = Field(alias="CONF_PASSWORD")
    conf_verify_ssl: bool = Field(default=False, alias="CONF_VERIFY_SSL")

    sync_rate_limit_per_minute: int = Field(default=10, alias="SYNC_RATE_LIMIT_PER_MINUTE")
    sync_request_timeout_seconds: int = Field(default=30, alias="SYNC_REQUEST_TIMEOUT_SECONDS")
    sync_admin_token: str = Field(default="change-me", alias="SYNC_ADMIN_TOKEN")

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    llm_base_url: str = Field(alias="LLM_BASE_URL")
    llm_model: str = Field(alias="LLM_MODEL")
    llm_dep_ticket: str | None = Field(default=None, alias="LLM_DEP_TICKET")
    llm_send_system_name: str | None = Field(default=None, alias="LLM_SEND_SYSTEM_NAME")
    llm_user_id: str | None = Field(default=None, alias="LLM_USER_ID")
    llm_user_type: str | None = Field(default=None, alias="LLM_USER_TYPE")

    vlm_base_url: str = Field(alias="VLM_BASE_URL")
    vlm_model: str = Field(alias="VLM_MODEL")
    vlm_dep_ticket: str | None = Field(default=None, alias="VLM_DEP_TICKET")
    vlm_send_system_name: str | None = Field(default=None, alias="VLM_SEND_SYSTEM_NAME")
    vlm_user_id: str | None = Field(default=None, alias="VLM_USER_ID")
    vlm_user_type: str | None = Field(default=None, alias="VLM_USER_TYPE")

    database_url: str = Field(alias="DATABASE_URL")
    wiki_root: Path = Field(alias="WIKI_ROOT")
    cache_root: Path = Field(alias="CACHE_ROOT")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
