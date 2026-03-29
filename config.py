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
        extra="ignore",
    )

    # --- GHL ---
    ghl_api_key: str = ""
    ghl_location_id: str = ""
    ghl_webhook_secret: str = ""
    ghl_calendar_id: str = "Igep2NHQN6syeVSs5zz1"
    ghl_rvm_workflow_id: str = ""

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

    # --- Calendar Email Domain (for dummy GCal ↔ Close linking emails) ---
    calendar_email_domain: str = "appt.invalid"

    # --- Close.com ---
    close_api_key: str = ""
    close_appointment_activity_type_id: str = "actitype_6awVkZoRuXH1FWUd1F97CH"
    close_sms_from_number: str = ""
    close_webhook_secret: str = ""

    # --- Google Calendar (Service Account) ---
    google_service_account_json: str = ""
    google_calendar_id: str = "primary"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_refresh_token: str = ""

    # --- Twilio (Conference Bridge) ---
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = "+18446813690"

    # --- Quo (OpenPhone) ---
    quo_api_key: str = ""

    # --- Plaid (Phase 2) ---
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
