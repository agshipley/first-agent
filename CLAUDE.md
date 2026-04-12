# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**PERMITS_PROJECT.md is the source of truth for the permits intelligence engine — the art commissioning opportunity scoring system. Read it before making any changes to the permits/ directory or permits-related routes.**

Lead generation AI agent for Tre Borden/Co, a Los Angeles creative studio. The agent uses Claude with web search to find potential clients in two market segments: **corporate** (real estate developers, architecture firms) and **public sector** (municipal agencies, universities, transit authorities pursuing percent-for-art opportunities). Leads are saved to an Excel spreadsheet (`leads.xlsx`).

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run web server (development, port 5000)
python app.py

# Run CLI agent (interactive, prompts for segment)
python agent.py

# Test API connectivity
python hello.py

# Production server
gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120
```

Set `ANTHROPIC_API_KEY` in `.env` before running.

## Architecture

Three Python modules + a Flask web app:

- **`app.py`** — Flask server with SSE streaming. The `/run` route executes the Claude agent loop and streams live status updates to the browser. `/leads` returns existing leads from the spreadsheet. `/download` serves `leads.xlsx`.
- **`agent.py`** — Standalone CLI version of the same agent loop. Useful for running searches without the web UI.
- **`tools.py`** — All Excel read/write operations. `save_leads_to_spreadsheet()` deduplicates by company name and writes to separate "Corporate"/"Public Sector" sheets. `get_existing_leads_for_segment()` is called before each search run to give Claude context on what's already been found.
- **`templates/index.html`** — Single-page UI with segment selector, real-time SSE log, and lead cards with ICP score badges.

### Agent Loop Pattern

Both `app.py` and `agent.py` run the same agentic loop:
1. Pass existing leads + system prompt (segment-specific) to Claude
2. Claude calls `web_search` (built-in server-side tool) autonomously
3. When done, Claude calls `save_leads_to_spreadsheet` with structured lead data
4. Rate-limit errors trigger a 60-second retry wait

### Data Schema

Leads stored in `leads.xlsx` with columns: `Company Name | Type | Location | Why They're a Lead | Company Website | Source URL | Potential Contact | ICP Score | Notes | Date Found`

### Persistent Storage

`leads.xlsx` is the only datastore — no database. The file is gitignored. The app reads it at startup to populate existing leads for deduplication before each new search.

## Key Details

- Model used: `claude-sonnet-4-6` (both web and CLI paths)
- ICP scoring: 1–10 scale with different rubrics per segment; public sector rejects expired RFP deadlines
- The `web_search` tool is a built-in Anthropic server-side tool — it cannot be called directly from client code
- SSE streaming in `/run` uses `flask.Response` with `text/event-stream` content type

## Developer Preferences

- Provide complete, working files — not fragments or partial diffs
- Be honest about what's done vs. what's untested
- Correct technical terminology when used imprecisely — this is a learning project
- No filler or speculation — provide the fix, or say you don't know
- Be cost-conscious — suggest zero-cost testing (fake data, local-only) whenever possible
- Think through implications before proposing changes to production code

## Lessons Learned

- web_search is a server-side tool (Anthropic executes the search), but the API still requires an empty tool_result for every tool_use block before the next API call — always send one
- Railway auto-deploys from main on git push
- Port 5000 is occupied by AirPlay Receiver on macOS — use PORT=5001 for local testing
- Use test_formatting.py with fake data to test spreadsheet changes without API cost
- Back-to-back search runs can trigger rate limiting — space them out
- The early return after save_leads_to_spreadsheet in app.py is intentional to avoid Railway's connection timeout — do not remove it