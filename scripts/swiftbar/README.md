# FalconConnect SwiftBar 3 Way Bridge Controls

This installs a SwiftBar v0 menu bar control pane for the FalconConnect 3 Way Bridge.

## What it does

- Polls `https://falconnect.org/api/conference/bridge/live` every 5 seconds.
- Shows idle/live/3WAY/carrier status in the macOS menu bar.
- Finds a live Close-started bridge.
- Upgrades to conference.
- Adds carrier favorites.
- Shows dial instructions for the selected carrier.
- Mutes, unmutes, holds, unholds, and drops lead/Seb/carrier participants.
- Ends the bridge.

## Install

```bash
cd /Users/clawdolf/falconnect
scripts/swiftbar/install-swiftbar-bridge.sh
```

SwiftBar plugin path:

```text
~/Library/Application Support/SwiftBar/Plugins/fc-bridge.5s.py
```

Config path:

```text
~/.config/falconconnect/bridge.env
```

Config format:

```bash
FC_BASE_URL=https://falconnect.org
FC_MENU_BAR_TOKEN=<same-token-as-render>
```

## Backend token

FalconConnect accepts the SwiftBar token only on bridge-control endpoints. Browser auth still uses Clerk.

Set this Render env var:

```bash
FC_MENU_BAR_TOKEN=<long-random-token>
```

The token maps to `CLERK_ADMIN_USER_ID`, so ownership checks still apply.

If `FC_MENU_BAR_TOKEN` is missing or blank in FalconConnect, menu-bar token auth fails closed.

## Verify locally

```bash
FC_BASE_URL=https://falconnect.org FC_MENU_BAR_TOKEN= python3 scripts/swiftbar/fc-bridge.5s.py
python3 scripts/swiftbar/fc-bridge-action.py
PYTHONDONTWRITEBYTECODE=1 python3 -m py_compile routers/conference.py config.py scripts/swiftbar/fc-bridge.5s.py scripts/swiftbar/fc-bridge-action.py
```

## Troubleshooting

- `FC Bridge: config`: local token missing or placeholder token still present.
- `FC Bridge: idle`: no active bridge found.
- `FC Bridge: err`: API rejected the token, route failed, or FalconConnect is down.
- Last action/error lines are cached under `~/.cache/falconconnect/`.
