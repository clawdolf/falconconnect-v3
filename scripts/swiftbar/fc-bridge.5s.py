#!/usr/bin/env python3
"""SwiftBar plugin for FalconConnect 3 Way Bridge controls."""

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "falconconnect" / "bridge.env"
CACHE_DIR = Path.home() / ".cache" / "falconconnect"
CACHE_PATH = CACHE_DIR / "bridge.json"
ERROR_PATH = CACHE_DIR / "bridge-error.txt"
ACTION_HELPER_PATH = Path.home() / ".local" / "share" / "falconconnect" / "fc-bridge-action.py"
DEFAULT_BASE_URL = "https://falconnect.org"
SYSTEM_CA_FILES = (
    "/private/etc/ssl/cert.pem",
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
)
PHONE_ICON = "📞︎"


def ssl_context():
    for cafile in SYSTEM_CA_FILES:
        if Path(cafile).exists():
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def load_config():
    data = {}
    if CONFIG_PATH.exists():
        for raw in CONFIG_PATH.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return {
        "base_url": os.environ.get("FC_BASE_URL") or data.get("FC_BASE_URL") or DEFAULT_BASE_URL,
        "token": os.environ.get("FC_MENU_BAR_TOKEN") or data.get("FC_MENU_BAR_TOKEN") or "",
    }


def swift(text):
    return str(text or "").replace("\n", " / ").replace("|", "¦").strip()


def attr_path(path):
    return str(path).replace(" ", "\\ ")


def read_cache():
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def read_error():
    try:
        msg = ERROR_PATH.read_text().strip()
        if not msg:
            return ""
        age = time.time() - ERROR_PATH.stat().st_mtime
        if age > 120:
            return ""
        return msg
    except Exception:
        return ""


def api_get(path, cfg):
    url = cfg["base_url"].rstrip("/") + path
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {cfg['token']}",
            "Accept": "application/json",
            "User-Agent": "FalconConnect-SwiftBar/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8, context=ssl_context()) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, {}
        body = exc.read().decode("utf-8", errors="replace")[:200]
        return exc.code, {"error": body or str(exc)}
    except Exception as exc:
        return 0, {"error": str(exc)}


def action_line(label, action, *params):
    helper = ACTION_HELPER_PATH if ACTION_HELPER_PATH.exists() else Path(__file__).with_name("fc-bridge-action.py")
    parts = [
        f"{swift(label)} | bash={attr_path(helper)}",
        f"param1={action}",
    ]
    for idx, param in enumerate(params, start=2):
        parts.append(f"param{idx}={swift(param)}")
    parts.extend(["terminal=false", "refresh=true"])
    return " ".join(parts)


def title_for(status):
    if status in {"conference_live", "upgrade_pending"}:
        return f"{PHONE_ICON} 3WAY"
    if status in {"carrier_connected", "dialing_carrier"}:
        return f"{PHONE_ICON} carrier"
    if status in {"transfer_received", "close_connected", "waiting_for_transfer"}:
        return f"{PHONE_ICON} LIVE"
    if status == "ended":
        return PHONE_ICON
    return PHONE_ICON


def fmt_duration(seconds):
    if seconds in (None, ""):
        return ""
    try:
        seconds = int(seconds)
    except Exception:
        return ""
    minutes, sec = divmod(max(seconds, 0), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {sec}s"
    return f"{minutes}m {sec}s"


def participant_present(participants, name):
    p = (participants or {}).get(name) or {}
    return bool(p.get("call_sid") or p.get("phone") or p.get("status") not in (None, "", "not_connected"))


def print_common(cfg, cache):
    err = read_error()
    if err:
        print("---")
        print(f"Last error: {swift(err)}")
    print("---")
    print(action_line("Refresh", "refresh"))
    print(f"Open FC | href={cfg['base_url'].rstrip('/')}")
    print(f"Config: {CONFIG_PATH}")
    last = cache.get("last_action")
    if last:
        print(f"Last action: {swift(last)}")


def main():
    cfg = load_config()
    cache = read_cache()
    if not cfg["token"] or cfg["token"].startswith("paste-") or cfg["token"].startswith("change-me"):
        print(f"{PHONE_ICON} config")
        print("---")
        print("Missing FC_MENU_BAR_TOKEN")
        print(f"Create/edit: {CONFIG_PATH}")
        print("FC_BASE_URL=https://falconnect.org")
        print("FC_MENU_BAR_TOKEN=<token>")
        return

    status, live = api_get("/api/conference/bridge/live", cfg)
    if status == 404:
        print(PHONE_ICON)
        print("---")
        print("No live bridge found")
        print(action_line("Find Live Bridge", "find-live"))
        print_common(cfg, cache)
        return
    if status != 200:
        print(f"{PHONE_ICON} err")
        print("---")
        print(f"API status: {status}")
        print(swift((live or {}).get("error", "Bridge API error")))
        print_common(cfg, cache)
        return

    if live.get("status") == "ended":
        print(PHONE_ICON)
        print("---")
        print("No live bridge found")
        print(action_line("Find Live Bridge", "find-live"))
        print_common(cfg, cache)
        return

    conf_id = live.get("conf_id") or cache.get("conf_id") or ""
    title = title_for(live.get("status"))
    print(title)
    print("---")
    print(f"Lead: {swift(live.get('lead_phone', ''))}")
    print(f"Status: {swift(live.get('status', ''))}")
    duration = fmt_duration(live.get("duration_seconds"))
    if duration:
        print(f"Duration: {duration}")
    if live.get("carrier_phone"):
        print(f"Carrier: {swift(live.get('carrier_phone'))}")
    print(f"Bridge: {swift(conf_id)}")
    selected = cache.get("selected_favorite") or {}
    instructions = selected.get("dial_instructions") or cache.get("dial_instructions")
    if instructions:
        print("---")
        label = selected.get("label") or "Carrier instructions"
        print(swift(label))
        print(swift(instructions))

    print("---")
    print(action_line("Find Live Bridge", "find-live"))
    if conf_id:
        print(action_line("Upgrade to Conference", "upgrade", conf_id))
        print(action_line("End Bridge", "end", conf_id))

    favorites_status, favorites = api_get("/api/conference/carrier-favorites", cfg)
    if conf_id and favorites_status == 200 and isinstance(favorites, list) and favorites:
        print("---")
        print("Carrier Favs")
        for fav in favorites:
            label = f"Add {fav.get('carrier_name', 'Carrier')} — {fav.get('carrier_dept', '')}".strip()
            print(action_line(label, "add-carrier", conf_id, fav.get("id", "")))
    elif favorites_status not in (200, 404):
        print("---")
        print(f"Carrier favorites error: {favorites_status}")

    participants = live.get("participants") or {}
    if conf_id and participants:
        print("---")
        print("Participant Controls")
        for name, label in (("lead", "Lead"), ("seb", "Seb/Close"), ("carrier", "Carrier")):
            if not participant_present(participants, name):
                continue
            p = participants.get(name) or {}
            state = []
            if p.get("muted"):
                state.append("muted")
            if p.get("hold"):
                state.append("hold")
            suffix = f" ({', '.join(state)})" if state else ""
            print(f"{label}{suffix}")
            print(action_line(f"  Mute {label}", "mute", conf_id, name))
            print(action_line(f"  Unmute {label}", "unmute", conf_id, name))
            print(action_line(f"  Hold {label}", "hold", conf_id, name))
            print(action_line(f"  Unhold {label}", "unhold", conf_id, name))
            print(action_line(f"  Drop {label}", "drop", conf_id, name))

    print_common(cfg, cache)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"{PHONE_ICON} err")
        print("---")
        print(f"Plugin error: {swift(exc)}")
        sys.exit(0)
