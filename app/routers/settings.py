import logging
from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/settings", tags=["Settings"])

# Whitelist of editable settings
EDITABLE_FIELDS = {
    "refresh_interval",
    "max_retries",
    "log_level",
    "rate_limit_enabled",
    "rate_limit_window",
    "rate_limit_max",
    "health_check_enabled",
    "health_check_interval",
    "rotation_strategy",
    "max_concurrent_per_account",
    "model_whitelist",
    "usage_stats_enabled",
    "usage_stats_interval",
    "usage_stats_retention_days",
    "jitter_enabled",
    "version_sync_enabled",
}

# Type mapping for validation
FIELD_TYPES = {
    "refresh_interval": int,
    "max_retries": int,
    "log_level": str,
    "rate_limit_enabled": bool,
    "rate_limit_window": int,
    "rate_limit_max": int,
    "health_check_enabled": bool,
    "health_check_interval": int,
    "rotation_strategy": str,
    "max_concurrent_per_account": int,
    "model_whitelist": str,
    "usage_stats_enabled": bool,
    "usage_stats_interval": int,
    "usage_stats_retention_days": int,
    "jitter_enabled": bool,
    "version_sync_enabled": bool,
}


class SettingsResponse(BaseModel):
    """Grouped settings response"""
    performance: Dict[str, Any] = Field(description="Performance-related settings")
    rate_limiting: Dict[str, Any] = Field(description="Rate limiting configuration")
    health_check: Dict[str, Any] = Field(description="Health check configuration")
    account_management: Dict[str, Any] = Field(description="Account rotation settings")
    usage_stats: Dict[str, Any] = Field(description="Usage statistics settings")
    models: Dict[str, Any] = Field(description="Model configuration")
    logging: Dict[str, Any] = Field(description="Logging configuration")


class SettingsUpdateRequest(BaseModel):
    """Request body for updating settings"""
    settings: Dict[str, Any] = Field(description="Key-value pairs of settings to update")

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        for key in v.keys():
            if key not in EDITABLE_FIELDS:
                raise ValueError(f"Setting '{key}' is not editable")
        return v


def _get_grouped_settings() -> Dict[str, Dict[str, Any]]:
    """Get current settings grouped by category"""
    return {
        "performance": {
            "refresh_interval": settings.refresh_interval,
            "max_retries": settings.max_retries,
            "jitter_enabled": settings.jitter_enabled,
        },
        "rate_limiting": {
            "rate_limit_enabled": settings.rate_limit_enabled,
            "rate_limit_window": settings.rate_limit_window,
            "rate_limit_max": settings.rate_limit_max,
        },
        "health_check": {
            "health_check_enabled": settings.health_check_enabled,
            "health_check_interval": settings.health_check_interval,
        },
        "account_management": {
            "rotation_strategy": settings.rotation_strategy,
            "max_concurrent_per_account": settings.max_concurrent_per_account,
        },
        "usage_stats": {
            "usage_stats_enabled": settings.usage_stats_enabled,
            "usage_stats_interval": settings.usage_stats_interval,
            "usage_stats_retention_days": settings.usage_stats_retention_days,
        },
        "models": {
            "model_whitelist": settings.model_whitelist,
        },
        "logging": {
            "log_level": settings.log_level,
        },
    }


def _update_env_file(updates: Dict[str, Any]) -> None:
    """Update .env file with new values"""
    env_path = Path(".env")

    if not env_path.exists():
        lines = []
        for key, value in updates.items():
            env_key = key.upper()
            lines.append(f"{env_key}={value}")
        env_path.write_text("\n".join(lines) + "\n")
        logger.info(f"Created .env file with {len(updates)} settings")
        return

    # Read existing content
    content = env_path.read_text()
    lines = content.splitlines()

    # Track which keys were updated
    updated_keys = set()
    new_lines = []

    # Update existing lines
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key_part = line.split("=", 1)[0].strip()
            matching_update = None
            for update_key, update_value in updates.items():
                if update_key.upper() == key_part.upper():
                    matching_update = (update_key, update_value)
                    break
            if matching_update:
                key, value = matching_update
                new_lines.append(f"{key_part}={value}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Add new keys that weren't in the file
    for key, value in updates.items():
        if key not in updated_keys:
            env_key = key.upper()
            new_lines.append(f"{env_key}={value}")

    # Write back to file
    env_path.write_text("\n".join(new_lines) + "\n")
    logger.info(f"Updated .env file with {len(updates)} settings")


def _update_in_memory_settings(updates: Dict[str, Any]) -> None:
    """Update in-memory settings object"""
    for key, value in updates.items():
        # Validate type
        expected_type = FIELD_TYPES.get(key)
        if expected_type and not isinstance(value, expected_type):
            raise ValueError(f"Setting '{key}' must be of type {expected_type.__name__}")

        # Update using object.__setattr__ to bypass pydantic immutability
        object.__setattr__(settings, key, value)
        logger.info(f"Updated in-memory setting: {key}={value}")


@router.get("", response_model=SettingsResponse)
async def get_settings() -> SettingsResponse:
    """Get current editable settings, grouped by category."""
    grouped = _get_grouped_settings()
    return SettingsResponse(**grouped)


@router.post("", response_model=SettingsResponse)
async def update_settings(request: SettingsUpdateRequest) -> SettingsResponse:
    """Update application settings. Updates both .env file and in-memory settings."""
    try:
        # Validate all settings before making any changes
        for key, value in request.settings.items():
            expected_type = FIELD_TYPES.get(key)
            if expected_type and not isinstance(value, expected_type):
                raise HTTPException(
                    status_code=400,
                    detail=f"Setting '{key}' must be of type {expected_type.__name__}, got {type(value).__name__}"
                )

        # Update .env file
        _update_env_file(request.settings)

        # Update in-memory settings
        _update_in_memory_settings(request.settings)

        # Return updated settings
        grouped = _get_grouped_settings()
        return SettingsResponse(**grouped)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update settings: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")
