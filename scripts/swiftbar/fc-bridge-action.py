#!/usr/bin/env python3
"""Action helper for the FalconConnect SwiftBar bridge plugin."""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "falconconnect" / "bridge.env"
CACHE_DIR = Path.home() / ".cache" / "falconconnect"
CACHE_PATH = CACHE_DIR / "bridge.json"
ERROR_PATH = CACHE_DIR / "bridge-error.txt"
DEFAULT_BASE_URL = "https://falconnect.org"
SYSTEM_CA_FILES = (
    "/private/etc/ssl/cert.pem",
    "/etc/ssl/cert.pem",
    "/etc/ssl/certs/ca-certificates.crt",
)


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


def ensure_cache_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def read_cache():
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def write_cache(data):
    ensure_cache_dir()
    CACHE_PATH.write_text(json.dumps(data, indent=2, sort_keys=True))


def write_error(message):
    ensure_cache_dir()
    ERROR_PATH.write_text(str(message)[:500])


def clear_error():
    try:
        ERROR_PATH.unlink()
    except FileNotFoundError:
        pass


def request(method, path, cfg, payload=None):
    if not cfg["token"] or cfg["token"].startswith("paste-") or cfg["token"].startswith("change-me"):
        raise RuntimeError(f"Missing FC_MENU_BAR_TOKEN in {CONFIG_PATH}")
    url = cfg["base_url"].rstrip("/") + path
    body = None
    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/json",
        "User-Agent": "FalconConnect-SwiftBar/1.0",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=12, context=ssl_context()) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"{method} {path} failed: {exc.code} {raw}") from exc


def find_favorite(favorites, favorite_id):
    for fav in favorites:
        if str(fav.get("id")) == str(favorite_id):
            return fav
    raise RuntimeError(f"Carrier favorite not found: {favorite_id}")


def usage():
    return (
        "Usage: fc-bridge-action.py refresh | find-live | upgrade <conf_id> | end <conf_id> | "
        "add-carrier <conf_id> <favorite_id> | mute|unmute|hold|unhold|drop <conf_id> <participant>"
    )


def main(argv):
    cfg = load_config()
    cache = read_cache()
    if len(argv) < 2:
        msg = usage()
        print(msg)
        write_error(msg)
        return 0

    action = argv[1]
    try:
        if action == "refresh":
            cache["last_action"] = "refreshed"
            write_cache(cache)
            clear_error()
            return 0

        if action == "find-live":
            live = request("GET", "/api/conference/bridge/live", cfg)
            cache["conf_id"] = live.get("conf_id")
            cache["last_action"] = "found live bridge"
            write_cache(cache)
            clear_error()
            return 0

        if action in {"upgrade", "end"}:
            if len(argv) < 3:
                raise RuntimeError(f"{action} requires conf_id")
            conf_id = argv[2]
            request("POST", f"/api/conference/{urllib.parse.quote(conf_id)}/{action}", cfg, {})
            cache["conf_id"] = conf_id
            cache["last_action"] = action
            write_cache(cache)
            clear_error()
            return 0

        if action == "add-carrier":
            if len(argv) < 4:
                raise RuntimeError("add-carrier requires conf_id and favorite_id")
            conf_id, favorite_id = argv[2], argv[3]
            favorites = request("GET", "/api/conference/carrier-favorites", cfg)
            fav = find_favorite(favorites, favorite_id)
            label = f"{fav.get('carrier_name', 'Carrier')} {fav.get('carrier_dept', '')}".strip()
            payload = {"carrier_phone": fav.get("carrier_number", ""), "carrier_label": label}
            request("POST", f"/api/conference/{urllib.parse.quote(conf_id)}/carrier", cfg, payload)
            cache.update({
                "conf_id": conf_id,
                "last_action": f"added {label}",
                "selected_favorite": {
                    "id": fav.get("id"),
                    "label": label,
                    "dial_instructions": fav.get("dial_instructions", ""),
                },
                "dial_instructions": fav.get("dial_instructions", ""),
            })
            write_cache(cache)
            clear_error()
            return 0

        if action in {"mute", "unmute", "hold", "unhold", "drop"}:
            if len(argv) < 4:
                raise RuntimeError(f"{action} requires conf_id and participant")
            conf_id, participant = argv[2], argv[3]
            request("POST", f"/api/conference/{urllib.parse.quote(conf_id)}/{action}/{urllib.parse.quote(participant)}", cfg, {})
            cache.update({"conf_id": conf_id, "last_action": f"{action} {participant}"})
            write_cache(cache)
            clear_error()
            return 0

        raise RuntimeError(usage())
    except Exception as exc:
        write_error(exc)
        print(exc)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
