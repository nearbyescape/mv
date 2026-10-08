from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import urlsplit
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MV_", env_file=".env", extra="ignore")
    environment: str = "local"
    database_url: str = "sqlite:///./mv_signal.db"
    dev_api_token: str = "mv-local-preview-only"
    auth_required: bool = False
    public_origin: str = "http://127.0.0.1:3100"
    service_key: str = ""
    session_hours: int = 12
    paper_enabled: bool = False
    maintenance: bool = False
    ai_enabled: bool = False
    openrouter_key: str = ""
    ai_model: str = "deepseek/deepseek-v4-pro-0813"
    ai_daily_requests: int = 20
    signal_session_enabled: bool = False
    telegram_enabled: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    telegram_start_at: int = 0
    daily_report_start_at: int = 0

    def model_post_init(self, __context):
        import os
        for name in ("service_key", "database_url", "openrouter_key", "telegram_token"):
            filename = os.environ.get("MV_" + name.upper() + "_FILE")
            if filename:
                setattr(self, name, Path(filename).read_text(encoding="utf-8").strip())

    def check_local_only(self) -> None:
        if self.environment not in ("local", "production"):
            raise RuntimeError("Unsupported deployment environment")
        origin = urlsplit(self.public_origin)
        if origin.path or origin.query or origin.fragment or origin.username or not origin.hostname:
            raise RuntimeError("Public origin must be an exact origin without a path")
        if not 1 <= self.session_hours <= 24:
            raise RuntimeError("Sessions must expire within 24 hours")
        if not 1 <= self.ai_daily_requests <= 20 or self.ai_model != "deepseek/deepseek-v4-pro-0813":
            raise RuntimeError("AI requires the pinned model and a maximum of 20 requests per UTC day")
        if self.telegram_enabled:
            import re
            if not re.fullmatch(r"-?[1-9][0-9]{0,15}", self.telegram_chat_id) or self.telegram_start_at <= 0:
                raise RuntimeError("Telegram requires a numeric destination and an activation timestamp")
        if self.environment == "production":
            if not self.auth_required or origin.scheme != "https" or len(self.service_key) < 32 or self.service_key == self.dev_api_token or not self.database_url.startswith("postgresql+psycopg://") or self.paper_enabled:
                raise RuntimeError("Production requires invite-only authentication, HTTPS origin, a strong service key, PostgreSQL and disabled paper observation")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.check_local_only()
    return settings
