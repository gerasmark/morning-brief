from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./data.db"
    timezone: str = "Europe/Athens"

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
        "https://www.iefimerida.gr,"
        "https://www.news247.gr"
    )
    strike_feed_limit: int = 24
    strike_feed_use_llm: bool = False

    schedule_hour: int = 8
    schedule_minute: int = 30

    cors_allow_origins: str = "*"

    @property
    def tzinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
