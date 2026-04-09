# GHL Dashboard Token Refresh

**Status:** Action needed — token expired
**Created:** 2026-04-09

## Problem

GoHighLevel dashboard token is expired. Needs manual refresh in GHL settings.

## Impact

Any GHL API calls that depend on the dashboard token will fail until refreshed.

## What's Needed

- Seb logs into GHL dashboard
- Regenerates the API token
- Updates `GHL_API_KEY` in Render environment variables

## Next Step

Manual action from Seb — can't be automated.
