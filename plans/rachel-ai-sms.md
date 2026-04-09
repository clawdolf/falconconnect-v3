# Rachel AI — Inbound/Outbound SMS Agent

**Status:** Built, blocked on A2P 10DLC approval
**Created:** 2026-04-09

## Purpose

AI SMS agent that handles inbound replies and can do outbound follow-ups. Lives on Mac mini, receives inbound SMS via Close webhook, builds context from lead data, replies via Close SMS API.

## Architecture

- Receives inbound SMS via Close webhook/API
- Pulls lead context from Close + FalconConnect
- Builds prompt with conversation history (stored in Honcho)
- Calls LLM for response
- Replies via Close SMS API
- Writes notes/triggers to Close

## Blocker

**A2P 10DLC registration** — Trusted SMS approval submitted March 19, 2026. Need carrier approval before Rachel can send/receive SMS at scale.

## What's Built

- Full spec exists
- Mac mini environment ready
- Close API integration for SMS

## What's Needed

- A2P 10DLC approval
- End-to-end testing once approved
