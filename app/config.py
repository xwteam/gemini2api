import string
import secrets
import logging
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import field_validator

logger = logging.getLogger(__name__)

APP_VERSION = "1.6.4"


def _generate_api_key() -> str:
    chars = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(32))
    return f"sk-{suffix}"


class Settings(BaseSettings):
    gemini_psid: str = ""
    gemini_psidts: str = ""
    api_key: str = ""
    refresh_interval: int = 5
    max_retries: int = 3
    port: int = 5918
    log_level: str = "info"
    rate_limit_enabled: bool = False
    rate_limit_window: int = 60
    rate_limit_max: int = 10
    health_check_enabled: bool = True
    health_check_interval: int = 5
    accounts_file: str = "accounts.json"
    rotation_strategy: str = "round-robin"
    max_concurrent_per_account: int = 3
    fingerprint_config_path: str = "data/fingerprint.json"
    version_sync_enabled: bool = True
    version_sync_interval: int = 24
    jitter_enabled: bool = True
    usage_stats_enabled: bool = True
    usage_stats_interval: int = 300
    usage_stats_retention_days: int = 30
    model_whitelist: str = ""

    @field_validator("gemini_psid")
    @classmethod
    def psid_clean(cls, v: str) -> str:
        return v.strip().strip('"').strip("'").rstrip(";")

    @field_validator("gemini_psidts")
    @classmethod
    def clean_psidts(cls, v: str) -> str:
        return v.strip().strip('"').strip("'").rstrip(";")

    @field_validator("api_key")
    @classmethod
    def ensure_api_key(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return _generate_api_key()
        return v

    @field_validator("port")
    @classmethod
    def port_range(cls, v: int) -> int:
        if v < 1 or v > 65535:
            raise ValueError("PORT must be between 1 and 65535")
        return v

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()


def _persist_api_key():
    env_path = Path(".env")
    if not env_path.exists():
        return
    content = env_path.read_text()
    if "API_KEY=" in content:
        for line in content.splitlines():
            if line.startswith("API_KEY="):
                val = line.split("=", 1)[1].strip()
                if val:
                    return
    if "API_KEY=" in content:
        lines = content.splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("API_KEY="):
                new_lines.append(f"API_KEY={settings.api_key}")
            else:
                new_lines.append(line)
        env_path.write_text("\n".join(new_lines) + "\n")
    else:
        content = content.rstrip("\n") + f"\nAPI_KEY={settings.api_key}\n"
        env_path.write_text(content)
    logger.info(f"API Key generated: {settings.api_key}")


_persist_api_key()
