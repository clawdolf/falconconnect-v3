# FalconVerify Meta Pixel

**Status:** Blocked — waiting for real Pixel ID from Seb
**Created:** 2026-04-09

## Problem

FalconVerify (falconfinancial.org) has a placeholder Pixel ID. Site is live and tracking page views with a fake ID — zero data going to Meta.

## What's Needed

- Real Meta Pixel ID from Seb
- Update `PIXEL_ID` in Render environment variables
- Verify events fire correctly (PageView, Lead, Schedule)

## Current State

Site deployed at falconfinancial.org. Pixel code is wired up, just needs the real ID.
