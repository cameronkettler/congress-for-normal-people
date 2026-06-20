from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from packages.shared.topics import DEFAULT_MONITORING_TOPICS


class Settings(BaseSettings):
    database_url: str = "sqlite:///./civic_pulse.db"
    congress_api_key: str | None = None
    congress_api_timeout_seconds: float = 300.0
    congress_recent_api_timeout_seconds: float = 30.0
    fec_api_key: str | None = None
    fec_api_timeout_seconds: float = 60.0
    lobbying_disclosure_api_key: str | None = None
    lobbying_disclosure_base_url: str = "https://lda.gov/api/v1"
    lobbying_api_live: bool = False
    lobbying_api_timeout_seconds: float = 60.0
    census_geocoder_base_url: str = "https://geocoding.geo.census.gov/geocoder"
    census_geocoder_timeout_seconds: float = 30.0
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.4-mini"
    openai_api_live: bool = False
    openai_reasoning_effort: str = "low"
    openai_api_timeout_seconds: float = 120.0
    serpapi_api_key: str | None = None
    serpapi_enabled: bool = False
    serpapi_timeout_seconds: float = 20.0
    rep_position_search_results: int = 5
    monitoring_topics: str = DEFAULT_MONITORING_TOPICS
    monitoring_poll_limit: int = 10
    job_token: str | None = None
    session_token_bytes: int = 32
    password_hash_iterations: int = 210000
    web_cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_from: str = "alerts@civic-pulse.local"
    email_to: str = "demo@example.com"
    app_name: str = "Congress For Normal People"
    environment: str = Field(default="development")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def topics(self) -> list[str]:
        return [topic.strip() for topic in self.monitoring_topics.split(",") if topic.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
