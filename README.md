# FalconConnect v3

**Middleware layer for Falcon Financial** — dual GHL + Notion sync, iCal feed, analytics hub.

## Architecture

FalconConnect v3 is a clean FastAPI middleware that sits between:
- **GoHighLevel (GHL)** — primary CRM, dialer, pipeline
- **Notion** — lead tracking, appointment management, knowledge base

It provides:
- **Dual-push lead capture** — one POST, both systems updated
- **GHL → Notion webhook bridge** — appointments, stage changes, DNC mirrored automatically
- **iCal feed** — subscribe in any calendar app to see upcoming appointments and follow-ups
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
| `POST` | `/api/public/leads/capture` | Capture lead → GHL + Notion |
| `POST` | `/api/webhooks/ghl` | GHL webhook receiver → Notion sync |
| `GET` | `/api/calendar/seb.ics?token=...` | iCal feed from Notion |
| `GET` | `/api/analytics/daily` | Daily production metrics |
| `GET` | `/api/analytics/summary` | Aggregated summary |
| `GET` | `/api/admin/health` | Liveness probe |
| `GET` | `/api/admin/health/db` | Database connectivity |
| `GET` | `/api/admin/version` | Version info |

## Project Structure

```
├── main.py              # FastAPI app entry point
├── config.py            # pydantic-settings configuration
├── routers/             # API route handlers
│   ├── leads.py         # Lead capture (dual push)
│   ├── webhooks.py      # GHL → Notion bridge
│   ├── calendar.py      # iCal feed
│   ├── analytics.py     # Production metrics
│   └── admin.py         # Health + version
├── services/            # External API clients
│   ├── ghl.py           # GoHighLevel API
│   ├── notion.py        # Notion API
│   ├── calendar.py      # iCal generation
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
