from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    db_api_client_id: str = ""
    db_api_client_secret: str = ""
    db_api_base_url: str = "https://apis.deutschebahn.com"
    transport_rest_base_url: str = "https://v6.db.transport.rest"

    mariadb_host: str = "mariadb"
    mariadb_port: int = 3306
    mariadb_database: str = "bahnapp"
    mariadb_user: str = "bahnapp"
    mariadb_password: str = ""

    poll_worker_interval_seconds: int = 60
    discovery_hour_local: int = 4
    discovery_lookahead_days: int = 2
    default_max_umstiege: int = 2

    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8501/oauth2callback"
    allowed_emails: str = ""
    session_secret_key: str = "dev-secret-change-me"

    log_level: str = "INFO"
    tz: str = "Europe/Berlin"

    @property
    def allowed_emails_set(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

    @property
    def db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mariadb_user}:{self.mariadb_password}"
            f"@{self.mariadb_host}:{self.mariadb_port}/{self.mariadb_database}?charset=utf8mb4"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
