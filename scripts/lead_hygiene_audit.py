#!/usr/bin/env python3
"""CLI runner for the FalconConnect old lead hygiene audit.

DRY RUN ONLY. This script issues GET requests against Close (and optionally
GHL) and reads a Notion CSV export from disk. It NEVER writes to Close, GHL,
or Notion — the only side effect is creating report files on local disk.

Usage:
  # Fixture mode (no network, fastest sanity check)
  python scripts/lead_hygiene_audit.py --fixture-mode --output-dir ./out/audit

  # Live read-only mode against Close (requires CLOSE_API_KEY in env)
  python scripts/lead_hygiene_audit.py \
      --limit 100 \
      --status "Voicemail" \
      --notion-csv ./data/notion_export.csv \
      --output-dir ./out/audit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Make the project root importable when run as a script.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.lead_hygiene_collect import (
    run_audit_from_fixtures,
    run_audit_from_live,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Old lead hygiene dry-run audit.")
    p.add_argument("--output-dir", required=True, type=Path,
                   help="Directory to write CSV + JSON reports into.")
    p.add_argument("--fixture-mode", action="store_true",
                   help="Use bundled fixtures (no network, safe).")
    p.add_argument("--fixture-dir", type=Path, default=None,
                   help="Override fixture directory (fixture-mode only).")
    p.add_argument("--limit", type=int, default=100,
                   help="Max number of Close leads to audit (live mode).")
    p.add_argument("--status", type=str, default=None,
                   help='Filter Close leads by status name (e.g. Voicemail). '
                        'Sent as the search-syntax query status:"<value>" '
                        '— Close ignores raw status_label= on /lead/.')
    p.add_argument("--query", type=str, default=None,
                   help='Extra Close search-syntax clause AND-combined with '
                        '--status (e.g. \'lead_age:"60+ Mo"\').')
    p.add_argument("--notion-csv", type=Path, default=None,
                   help="Optional Notion CSV export for live mode.")
    p.add_argument("--recent-window-days", type=int, default=30,
                   help="Days within which an outbound touch blocks automation.")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[lead-hygiene] DRY RUN — no writes will be issued to Close/GHL/Notion.")
    print(f"[lead-hygiene] Output dir: {args.output_dir}")

    if args.fixture_mode:
        out = run_audit_from_fixtures(
            fixture_dir=args.fixture_dir or _ROOT / "data" / "fixtures" / "lead_hygiene",
            out_dir=args.output_dir,
            recent_window_days=args.recent_window_days,
            limit=args.limit,
        )
    else:
        out = asyncio.run(run_audit_from_live(
            out_dir=args.output_dir,
            limit=args.limit,
            status_label=args.status,
            recent_window_days=args.recent_window_days,
            notion_csv=args.notion_csv,
            extra_query=args.query,
        ))

    print(f"[lead-hygiene] CSV : {out['csv_path']}")
    print(f"[lead-hygiene] JSON: {out['json_path']}")
    print(f"[lead-hygiene] Summary: {json.dumps(out['summary'], indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
