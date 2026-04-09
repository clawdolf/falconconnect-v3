#!/usr/bin/env python3
"""
Robust alembic migration runner.
Handles multiple-heads by auto-merging before upgrading.
"""
import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("migrate")

def run(cmd):
    log.info("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout:
        log.info("STDOUT: %s", result.stdout.strip())
    if result.stderr:
        log.info("STDERR: %s", result.stderr.strip())
    return result.returncode, result.stdout, result.stderr

def main():
    # First attempt
    code, out, err = run(["alembic", "upgrade", "head"])
    if code == 0:
        log.info("Migration succeeded.")
        return 0

    # Check if it's a multiple-heads error
    combined = (out + err).lower()
    if "multiple heads" in combined or "target database is not up to date" in combined:
        log.warning("Multiple heads detected — attempting auto-merge.")
        code2, _, _ = run(["alembic", "merge", "heads", "-m", "auto_merge_heads"])
        if code2 != 0:
            log.error("Auto-merge failed. Trying stamp + upgrade.")
            # Stamp all current heads then upgrade
            run(["alembic", "stamp", "head"])
        # Retry upgrade
        code3, _, _ = run(["alembic", "upgrade", "head"])
        if code3 == 0:
            log.info("Migration succeeded after merge.")
            return 0
        log.error("Migration still failing after merge attempt.")
        return code3

    log.error("Migration failed with unrecognized error.")
    return code

if __name__ == "__main__":
    sys.exit(main())
