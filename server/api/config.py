"""Station configuration from environment."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    waypost_env: str = "development"
    waypost_data_dir: Path = Path("./data")
    waypost_sqlite_path: Path = Path("./data/waypost.db")
    waypost_log_level: str = "INFO"

    waypost_domain: str = "waypost.home.arpa"
    waypost_ssid: str = "WAYPOST"

    waypost_api_host: str = "0.0.0.0"
    waypost_api_port: int = 8000
    waypost_secret_key: str = "dev-only-change-me"

    waypost_lora_device: str = "/dev/waypost-lora"
    waypost_transport: Literal["mock", "reticulum", "serial", "serial_bridge", "heltec"] = "mock"
    waypost_radio_region: str = "US"

    waypost_registration_mode: Literal["OPEN", "INVITE_ONLY", "ADMIN_APPROVAL"] = "OPEN"
    # When True, HTTP APIs require a session (test env defaults False via property)
    waypost_auth_required: bool = True

    def ensure_data_dirs(self) -> None:
        self.waypost_data_dir.mkdir(parents=True, exist_ok=True)
        self.waypost_sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        (self.waypost_data_dir / "locker").mkdir(parents=True, exist_ok=True)

    @property
    def waypost_locker_dir(self) -> Path:
        return self.waypost_data_dir / "locker"


def get_settings() -> Settings:
    return Settings()
