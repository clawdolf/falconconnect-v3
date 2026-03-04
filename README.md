# FalconConnect v3

**Middleware layer for Falcon Financial** — dual GHL + Notion sync, iCal feeds, analytics hub.

## Architecture

FalconConnect v3 is a clean FastAPI middleware that sits between:
- **GoHighLevel (GHL)** — primary CRM, dialer, pipeline
- **Notion** — lead tracking, appointment management, knowledge base

It provides:
- **Dual-push lead capture** — one POST, both systems updated
- **GHL → Notion webhook bridge** — appointments, stage changes, DNC mirrored automatically
- **Two iCal feeds** — appointments and follow-ups as separate subscribable calendars
- **Analytics API** — daily production metrics (dials, contacts, appts, closes, premium)

## Quick Start

```bash
# Clone
git clone https://github.com/clawdolf/falconconnect-v3.git
cd falconconnect-v3

# Environment
cp .env.example .env
# Fill in your API keys

# Install
pip install -r requirements.txt

# Run (dev)
uvicorn main:app --reload --port 8000

# Run migrations (production)
alembic upgrade head
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Root liveness probe |
| `POST` | `/api/public/leads/capture` | Capture lead → GHL + Notion |
| `POST` | `/api/webhooks/ghl` | GHL webhook receiver → Notion sync |
| `GET` | `/api/calendar/appointments.ics?token=...` | iCal feed — appointments only |
| `GET` | `/api/calendar/followups.ics?token=...` | iCal feed — follow-ups only |
| `GET` | `/api/analytics/daily` | Daily production metrics |
| `GET` | `/api/analytics/summary` | Aggregated summary |
| `GET` | `/api/admin/health` | Admin liveness probe |
| `GET` | `/api/admin/health/db` | Database connectivity |
| `GET` | `/api/admin/version` | Version info |

### Calendar Feeds

Two separate iCal feeds so you can subscribe independently with different colors:

- **Appointments** — timed 1-hour events, 60-min + 24-hour reminders
  `GET /api/calendar/appointments.ics?token={CALENDAR_SECRET}`

- **Follow-Ups** — all-day events, 8am morning reminder
  `GET /api/calendar/followups.ics?token={CALENDAR_SECRET}`

Both secured with the same `CALENDAR_SECRET` token.

## Project Structure

```
├── main.py              # FastAPI app entry point
├── config.py            # pydantic-settings configuration
├── routers/             # API route handlers
│   ├── leads.py         # Lead capture (dual push)
│   ├── webhooks.py      # GHL → Notion bridge
│   ├── calendar.py      # iCal feeds (appointments + follow-ups)
│   ├── analytics.py     # Production metrics
│   └── admin.py         # Health + version
├── services/            # External API clients
│   ├── ghl.py           # GoHighLevel API
│   ├── notion.py        # Notion API
│   ├── calendar.py      # iCal generation (two builders)
│   └── plaid.py         # Plaid (Phase 2 stub)
├── models/              # Pydantic models
│   ├── lead.py          # LeadPayload
│   ├── webhook.py       # GHLWebhookPayload
│   └── xref.py          # LeadXref read model
├── db/                  # Database layer
│   ├── database.py      # Async engine + session
│   └── models.py        # ORM models
├── utils/               # Shared utilities
│   ├── age.py           # Age + LAge calculation
│   └── auth.py          # Auth + webhook verification
└── alembic/             # Database migrations
```

## Environment Variables

See `.env.example` for the full list with descriptions.

## Deployment

Configured for **Render** via `render.yaml`. Push to `main` to deploy.

## Previous Version

The v2 codebase is archived at [clawdolf/falconconnect-v2-archive](https://github.com/clawdolf/falconconnect-v2-archive).

---

*Falcon Financial — Seb Taillieu*
