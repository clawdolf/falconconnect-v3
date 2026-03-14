"""Centralized settings loaded from environment variables via pydantic-settings."""

from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_files() -> tuple[str, ...]:
    """Return .env file paths that exist — local first, then /etc/secrets."""
    candidates = [".env", "/etc/secrets/.env"]
    return tuple(p for p in candidates if Path(p).is_file())


class Settings(BaseSettings):
    """Application configuration.  All values come from env vars or .env file."""

    model_config = SettingsConfigDict(
        env_file=_resolve_env_files(),
        env_file_encoding="utf-8",
        # Always read from real environment — env vars override .env file
        env_ignore_empty=False,
    )

    # --- GHL ---
    ghl_api_key: str = ""
    ghl_location_id: str = ""
    ghl_webhook_secret: str = ""
    ghl_calendar_id: str = "Igep2NHQN6syeVSs5zz1"

    # --- Notion ---
    notion_token: str = ""
    notion_leads_db_id: str = "REPLACE_WITH_YOUR_NOTION_DATABASE_ID"

    # --- Calendar ---
    calendar_secret: str = ""

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./falconconnect.db"

    # --- Clerk Auth ---
    clerk_publishable_key: str = ""
    clerk_secret_key: str = ""

    # --- Notion → GHL Sync ---
    notion_ghl_sync_enabled: bool = True
    notion_ghl_sync_dry_run: bool = True
    notion_ghl_sync_after_date: str = "2026-03-03"
    notion_ghl_sync_interval: int = 300

    # --- Quo (OpenPhone) ---
    quo_api_key: str = ""

    # --- Plaid (Phase 2) ---
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    """Clear the cache and reload settings from env. Use after env var changes."""
    get_settings.cache_clear()
    return get_settings()
