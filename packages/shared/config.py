from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./civic_pulse.db"
    congress_api_key: str | None = None
    fec_api_key: str | None = None
    lobbying_disclosure_api_key: str | None = None
    lobbying_disclosure_base_url: str = "https://lda.gov/api/v1"
    lobbying_api_live: bool = False
    monitoring_topics: str = (
        "Artificial Intelligence,Healthcare,Housing,Energy,Defense,Technology,Privacy"
    )
    monitoring_poll_limit: int = 10
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    email_from: str = "alerts@civic-pulse.local"
    email_to: str = "demo@example.com"
    app_name: str = "Civic Pulse"
    environment: str = Field(default="development")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def topics(self) -> list[str]:
        return [topic.strip() for topic in self.monitoring_topics.split(",") if topic.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
