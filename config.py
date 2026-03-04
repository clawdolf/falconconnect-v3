"""Centralized settings loaded from environment variables via pydantic-settings."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.  All values come from env vars or .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

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

    # --- Plaid (Phase 2) ---
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"


@lru_cache
def get_settings() -> Settings:
    return Settings()
