from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    gemini_psid: str
    gemini_psidts: str = ""
    refresh_interval: int = 5
    max_retries: int = 3
    port: int = 4981
    log_level: str = "info"
    rate_limit_enabled: bool = False
    rate_limit_window: int = 60
    rate_limit_max: int = 10

    @field_validator("gemini_psid")
    @classmethod
    def psid_not_empty(cls, v: str) -> str:
        v = v.strip().strip('"').strip("'").rstrip(";")
        if not v:
            raise ValueError("GEMINI_PSID is required")
        return v

    @field_validator("gemini_psidts")
    @classmethod
    def clean_psidts(cls, v: str) -> str:
        return v.strip().strip('"').strip("'").rstrip(";")

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
