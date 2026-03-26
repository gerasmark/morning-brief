from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite:///./data.db"
    timezone: str = "Europe/Athens"
    root_path: str = ""

    llm_provider: str = "openai"
    llm_model: str = "gpt-4.1-mini"
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com"
    anthropic_api_key: str | None = None
    anthropic_base_url: str = "https://api.anthropic.com"
    ollama_base_url: str = "http://localhost:11434"
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_fallback_model: str = "openai/gpt-oss-120b"
    groq_reasoning_effort: str = "medium"

    weather_lat: float = 37.9838
    weather_lon: float = 23.7275
    weather_city_name: str = "Αθήνα"
    weather_ssl_verify: bool = True
    weather_ca_bundle: str | None = None
    weather_allow_insecure_fallback: bool = False
    birthdays_source_url: str = "https://www.eortologio.net/"
    birthdays_names_limit: int = 16
    quote_of_day_source_url: str = "https://www.lexigram.gr/ellinognosia/ImerasParoimia.php"
    strike_tag_urls: str = (
        "https://www.naftemporiki.gr/tag/apergia/,"
        "https://www.newsbomb.gr/tag/apergia,"
        "https://www.protothema.gr/tag/apergia/,"
        "https://www.tanea.gr/tag/%CE%B1%CF%80%CE%B5%CF%81%CE%B3%CE%AF%CE%B1/,"
        "https://www.iefimerida.gr/tag/apergia,"
        "https://www.news247.gr/tag/apergia/"
    )
    top_news_sites: str = (
        "https://www.naftemporiki.gr,"
        "https://www.newsbomb.gr,"
        "https://www.protothema.gr,"
        "https://www.tanea.gr,"
        "https://www.tovima.gr,"
        "https://www.iefimerida.gr,"
        "https://www.news247.gr"
    )
    strike_feed_limit: int = 24
    strike_feed_use_llm: bool = False

    schedule_hour: int = 8
    schedule_minute: int = 0

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_use_ssl: bool = False
    smtp_timeout_seconds: int = 20
    email_from_address: str | None = None
    email_from_name: str = "Πρωινό Briefing"
    resend_api_key: str | None = None
    resend_api_base_url: str = "https://api.resend.com"
    resend_timeout_seconds: int = 20
    resend_from_address: str = "onboarding@resend.dev"
    resend_ssl_verify: bool = True
    resend_ca_bundle: str | None = None
    resend_allow_insecure_fallback: bool = False

    auth_enabled: bool = False
    public_app_url: str | None = None
    session_secret_key: str = "change-me-before-production"
    auth_session_cookie_name: str = "morning_brief_admin"
    auth_session_max_age_seconds: int = 43200
    auth_cookie_secure: bool = True
    keycloak_base_url: str | None = None
    keycloak_realm: str | None = None
    keycloak_client_id: str | None = None
    keycloak_client_secret: str | None = None
    keycloak_admin_role: str = "briefing_admin"

    log_level: str = "INFO"
    app_log_level: str = "INFO"
    httpx_log_level: str = "WARNING"
    uvicorn_access_log_level: str = "WARNING"

    cors_allow_origins: str = "*"

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def resolve_database_url(database_url: str) -> str:
    for prefix in ("sqlite:///", "sqlite+aiosqlite:///"):
        if not database_url.startswith(prefix):
            continue

        path_part, separator, query = database_url[len(prefix) :].partition("?")
        if path_part == ":memory:" or path_part.startswith("/"):
            return database_url

        resolved = (BACKEND_DIR / path_part).resolve()
        suffix = f"?{query}" if separator else ""
        return f"{prefix}{resolved.as_posix()}{suffix}"

    return database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
