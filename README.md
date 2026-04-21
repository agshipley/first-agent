# Tre Borden /Co — Art Commission Lead Intelligence

An AI-powered lead generation and permit intelligence system for [Tre Borden /Co](https://www.treborden.com), a Los Angeles creative studio that curates and commissions art for corporate and public spaces. The system combines two complementary tools: an **AI lead finder** that uses Claude with web search to discover potential clients, and a **permit intelligence engine** that scores live building permit data for art commissioning relevance across Los Angeles, New York, and San Francisco.

**Live at:** Deployed on Railway (auto-deploys from `main`)
**License:** Apache 2.0

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [Lead Finder](#lead-finder)
- [Permit Intelligence Engine](#permit-intelligence-engine)
  - [Scoring Philosophy](#scoring-philosophy)
  - [Supported Cities](#supported-cities)
  - [Connector Architecture](#connector-architecture)
  - [Scoring Engine](#scoring-engine)
  - [Ordinance Data](#ordinance-data)
  - [Owner Pattern Matching](#owner-pattern-matching)
  - [Feedback System](#feedback-system)
- [API Reference](#api-reference)
- [Data Model](#data-model)
- [Testing](#testing)
- [Deployment](#deployment)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Contributing a New City](#contributing-a-new-city)

---

## Architecture Overview

```
                          +------------------+
                          |   Flask Web App  |
                          |     (app.py)     |
                          +--------+---------+
                                   |
                  +----------------+----------------+
                  |                                  |
         +--------v--------+             +----------v-----------+
         |   Lead Finder   |             |  Permit Intelligence |
         |   (agent loop)  |             |  Engine (permits/)   |
         +--------+--------+             +----------+-----------+
                  |                                  |
       +----------v----------+          +-----------+v-----------+
       | Anthropic API       |          | Socrata Open Data APIs |
       | (claude-sonnet-4-6) |          | (LA, NYC, SF)          |
       | + web_search tool   |          +----------+-------------+
       +---------------------+                     |
                                        +----------v-------------+
                                        | Scoring Engine         |
                                        | - Typology detection   |
                                        | - Owner pattern match  |
                                        | - Keyword signals      |
                                        | - Ordinance matching   |
                                        | - Valuation thresholds |
                                        +------------------------+
```

The system has two independent tools sharing a Flask server and Railway deployment:

| | Lead Finder | Permit Intelligence |
|---|---|---|
| **Question** | Who should Tre reach out to? | What's being built that might need art? |
| **Data source** | Open web via Claude + web_search | Structured municipal permit APIs |
| **Method** | AI-driven search and evaluation | Programmatic scoring (no LLM) |
| **Cost per query** | Anthropic API tokens | Free (municipal open data) |
| **Signal timing** | News, RFPs, announcements | Earliest possible (permit filed) |

---

## Quick Start

### Prerequisites

- Python 3.9+
- An [Anthropic API key](https://console.anthropic.com/) (for the Lead Finder only; the permit engine requires no API key)

### Install and Run

```bash
git clone https://github.com/agshipley/first-agent.git
cd first-agent

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# Run development server (port 5001 to avoid macOS AirPlay conflict)
PORT=5001 python app.py

# Run tests (no API key required)
pytest
```

### Available Pages

| URL | Page | Description |
|---|---|---|
| `/` | Lead Finder | AI-powered lead search with segment/geography filters |
| `/permits-monitor` | Opportunities | Live permit data scored for art commissioning relevance |
| `/reports` | Reports Archive | Saved deep dive research reports |
| `/report?id=<uuid>` | Individual Report | Deep dive report for a specific lead |

---

## Lead Finder

The Lead Finder uses Claude (`claude-sonnet-4-6`) with the built-in `web_search` server-side tool to find potential art commissioning clients. It operates in two segments:

- **Corporate** — Real estate developers, architecture firms, corporate clients commissioning art for private spaces
- **Public Sector** — Municipal agencies, transit authorities, universities with percent-for-art requirements

### How It Works

1. User selects segment, geography, budget range, and project stage
2. Flask streams an SSE connection to the browser
3. Claude runs an agentic loop: searches the web, evaluates leads, calls `save_leads_to_spreadsheet`
4. Results stream live to the UI as status updates, then render as scored lead cards
5. Leads are deduplicated and saved to `leads.xlsx` (the only datastore)

### Deep Dive

Clicking "Deep Dive" on any lead triggers a second AI research pass focused on that specific company/project. Claude researches five areas:

1. **Project Status & Timeline** — current phase, milestones, completion dates
2. **News & Media** — recent press coverage and announcements
3. **Existing Art Attachments** — has an art consultant or artist already been engaged?
4. **Key Principals** — decision-makers relevant to art commissioning
5. **Commissioning History** — prior art commissions by this organization

Deep dive reports are saved as JSON files in `{DATA_DIR}/reports/` and accessible from the Reports archive.

### ICP Scoring

Each lead receives an Ideal Customer Profile (ICP) score from 1-10:

| Score | Meaning |
|---|---|
| 1-3 | Relevant company type but no specific trigger |
| 4-6 | Active trigger exists but no evidence of art investment |
| 7-9 | Active trigger plus evidence of design investment |
| 10 | Active trigger, strong design culture, highly specific opportunity |

---

## Permit Intelligence Engine

The `permits/` module is a self-contained intelligence layer that ingests structured building permit data from municipal open data APIs and scores each permit for art commissioning relevance. It is entirely programmatic — no LLM calls, no external API costs.

### Scoring Philosophy

The engine was designed around the insight that **typology and owner signals are stronger predictors of actual art commissioning than ordinance triggers**. Research showed:

- LA's Private Arts Development Fee Program (PADFP) has historically been satisfied through in-lieu fees rather than commissioned art
- SF's Section 429 has generated approximately 53 commissions in 30 years
- In contrast, hotels almost always include art programs, healthcare campuses reliably commission healing arts, and public-sector projects with strong percent-for-art ordinances (LA Public Works, NYC DCLA, SF Art Enrichment) actively drive commissioning

The scoring engine reflects this hierarchy:

**Signal strength, strongest to weakest:**

1. **Typology** — What type of building is this?
   - Hotels: +3 (strongest single signal)
   - Healthcare facilities: +3
   - Airport/transit infrastructure: +3
   - Cultural/educational/civic: +2
   - Mixed-use/commercial: +1
   - Life sciences: +1
   - Industrial, warehouse, single-family, self-storage: hard-capped at None

2. **Owner Type** — Who is building it?
   - Major developers (Tishman Speyer, Hines, Brookfield, etc.): +2
   - Hotel brands (Hyatt, Four Seasons, Kimpton, etc.): +2
   - Healthcare systems (Kaiser, Cedars-Sinai, NYU Langone, etc.): +2
   - Airport/transit authorities (PANYNJ, LAWA, SFO): +2
   - Cultural institutions (Getty, Ford Foundation, etc.): +2
   - Public-sector agencies: +2
   - Major tech companies (Salesforce, Google, etc.): +1

3. **Keywords** — What does the project description say?
   - High-signal (hotel, lobby, plaza, atrium, museum, gallery, etc.): +1 each, capped at +3
   - Low-signal (warehouse, parking, tenant improvement, etc.): -2 each, uncapped

4. **Ordinance** — Is there a legal requirement?
   - Strong ordinances (LA Public Works, NYC DCLA, SF Art Enrichment): +2
   - Weak ordinances (LA PADFP, SF Section 429): +1

5. **Valuation** — How big is the project?
   - $50M+ landmark: +2
   - $20M+ large: +1

**Relevance levels:**

| Level | Score Threshold | Valuation Floor |
|---|---|---|
| High | >= 6 | Varies by typology (see below) |
| Medium | >= 3 | >= $2M |
| None | < 3 | Any |

**Typology-specific High valuation floors:**

| Typology | High Floor |
|---|---|
| Strong-ordinance public sector | $5M |
| Hotel | $15M |
| Healthcare | $20M |
| Cultural/educational | $20M |
| General commercial | $25M |
| Airport/transit | $50M |
| Life sciences | $75M |
| Landmark (any typology) | $50M |

### Supported Cities

| City | Data Source | Datasets | Ordinances | Status |
|---|---|---|---|---|
| Los Angeles | LADBS via data.lacity.org | `gwh9-jnip` (submitted), `pi9x-tg5x` (issued) | PADFP (1%, weak), Public Works (1%, strong) | Live |
| New York | NYC DOB via data.cityofnewyork.us | `w9ak-ipjd` (filings), `rbx6-tga4` (approved) | Public Art Allocation (1%, strong) | Live |
| San Francisco | SF DBI via data.sfgov.org | `p4e4-a5a7` (all statuses) | Art Enrichment (2%, strong), Section 429 (1%, weak) | Live |

### Connector Architecture

Each city connector translates a municipal data source into the canonical `CanonicalPermit` schema. The engine only reads this schema — it has no knowledge of Socrata field names or city-specific data formats.

```
permits/connectors/
├── base.py              # Abstract BaseConnector interface
├── socrata.py           # Generic Socrata API client (shared by all cities)
└── cities/
    ├── los_angeles.py   # LA-specific config: dataset IDs, field mappings, enum maps
    ├── new_york.py      # NYC-specific config + public-sector owner patterns
    └── san_francisco.py # SF-specific config (single dataset, status-based filtering)
```

The `SocrataConnector` handles:
- HTTP requests with timeout and retry (10s connect, 30s read, one retry)
- Response caching (1-hour TTL, in-memory)
- SoQL query building with server-side pre-filtering
- Row normalization to `CanonicalPermit`
- Deduplication across datasets (for cities with separate submitted/issued sources)

**Adding a new city** requires only a configuration file — no engine changes. See [Contributing a New City](#contributing-a-new-city).

### Scoring Engine

The scoring engine (`permits/engine.py`, 947 lines) processes `CanonicalPermit` records through a multi-factor pipeline:

```
CanonicalPermit
    |
    v
_is_irrelevant()          # Hard-cap: demolition, expired, single-family, industrial
    |
    v
_match_ordinances()       # Check city ordinances, compute art budget if triggered
    |
    v
_compute_score()          # Multi-factor: typology + owner + keywords + ordinance + valuation
    |                      # Returns (score, reasons, keyword_signals, scoring_factors, typology_flags)
    v
_determine_relevance()    # Map score to High/Medium/None with typology-specific valuation floors
    |
    v
_compute_ordinance_dependent()  # Flag permits that only score High/Medium because of ordinance
    |
    v
_format_budget()          # Strong ordinance: actual rate. Weak: heuristic. None: heuristic.
    |
    v
ScoredPermit              # Complete scored record with reasons, budget, stage, factors
```

Every scoring decision is logged in the `scoring_factors` field for debuggability:

```json
{
  "scoring_factors": [
    "typology:hotel:+3",
    "owner:+2",
    "keywords:+3",
    "permit_type:new:+2",
    "status:+1",
    "ordinance:weak:+1",
    "valuation:large:+1"
  ]
}
```

### Ordinance Data

Percent-for-art ordinance data is maintained in `permits/ordinances/data/percent_for_art.json`. Each ordinance includes:

- City, state, administering body
- Percentage rate (1% or 2%)
- Applicable project types and valuation thresholds
- In-lieu fee options
- `practical_strength` ("strong" or "weak") — determines scoring weight and budget calculation method
- `practical_notes` — plain-language explanation of historical enforcement

The engine treats strong and weak ordinances differently:

| | Strong | Weak |
|---|---|---|
| Score contribution | +2 | +1 |
| Budget calculation | Derived from ordinance rate | Heuristic (0.5%-1% of valuation) |
| Reason language | "actively drives commissioning" | "legal requirement exists but has historically driven few actual commissions" |
| Examples | LA Public Works, NYC DCLA, SF Art Enrichment | LA PADFP, SF Section 429 |

### Owner Pattern Matching

Owner/applicant name matching is configured in `permits/scoring/owner_patterns.json` with 7 categories (120+ patterns total):

| Category | Count | Score Bump | Examples |
|---|---|---|---|
| `developer_patterns` | 14 | +2 | Tishman Speyer, Hines, Brookfield, Kilroy Realty |
| `hotel_brand_patterns` | 35 | +2 | Hyatt, Four Seasons, Rosewood, Edition, Kimpton |
| `healthcare_system_patterns` | 37 | +2 | Kaiser, Cedars-Sinai, NYU Langone, UCSF Health |
| `airport_transit_patterns` | 10 | +2 | PANYNJ, LAWA, SFO, Public Art Fund |
| `cultural_institution_patterns` | 8 | +2 | Getty, Ford Foundation, Mellon Foundation |
| `tech_company_patterns` | 9 | +1 | Salesforce, Google, Anthropic, Stripe |
| `cultural_keywords` | 7 | +1 | museum, gallery, foundation, university |

Patterns are case-insensitive substring matches against the concatenation of `owner_name` and `applicant_name` fields. Hotel brand matches also upgrade the permit's typology detection to hotel (+3 typology bump).

### Feedback System

The Opportunities page includes a thumbs up/down feedback mechanism on each scored permit. Feedback is stored as append-only JSONL at `{DATA_DIR}/feedback.jsonl`.

Each record captures:
- Timestamp (ISO 8601)
- Permit ID and verdict (`up`, `down`, `unset`)
- Optional free-text reason (for thumbs-down)
- Relevance level at time of feedback
- City and active filter state
- User ID slot (currently `"default"` — ready for multi-user)

The GET endpoint returns the latest verdict per permit ID, enabling state restoration across sessions.

---

## API Reference

### Lead Finder

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Render Lead Finder page |
| `GET` | `/leads?segment=corporate&geography=New+York` | Return all leads for segment, optionally filtered by geography |
| `GET/POST` | `/run?segment=corporate&geography=...&budget=...&project_stage=...` | SSE stream — runs Claude agent loop, returns leads via `DONE\|[...]` event |
| `GET` | `/download` | Download `leads.xlsx` |
| `POST` | `/deep-dive` | SSE stream — runs deep dive research on a lead (JSON body) |
| `POST` | `/deep-dive/save` | Save deep dive findings to spreadsheet (`{ report_id }`) |
| `GET` | `/reports` | Render reports archive page |
| `GET` | `/api/reports` | List all saved reports (JSON array) |
| `GET` | `/api/reports/<uuid>` | Get a single report (JSON) |
| `GET` | `/report?id=<uuid>` | Render individual report page |

### Permit Intelligence

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/permits-monitor` | Render Opportunities page |
| `GET` | `/api/permits?city=los_angeles&source=submitted&min_valuation=5000000` | Scored permit opportunities (JSON) |
| `GET` | `/api/permits/metadata?city=los_angeles` | Connector metadata for a city |
| `POST` | `/api/feedback` | Submit feedback on a permit (`{ permit_id, verdict, reason?, ... }`) |
| `GET` | `/api/feedback?permit_ids=id1,id2` | Get latest feedback for listed permit IDs |

#### `/api/permits` Query Parameters

| Parameter | Default | Values |
|---|---|---|
| `city` | `los_angeles` | `los_angeles`, `new_york`, `san_francisco` |
| `source` | `submitted` | `submitted`, `issued`, `both` |
| `min_valuation` | `5000000` | Any number |
| `limit` | `50` | 1-200 |
| `art_budget_min` | `0` | Any number |
| `permit_type` | `all` | `all`, `new`, `alteration`, `addition` |
| `occupancy_type` | `all` | `all`, `commercial`, `apartment` |
| `sector` | `all` | `all`, `public`, `private` |
| `date_from` | (none) | `YYYY-MM-DD` |

Only permits scored **High** or **Medium** are returned. The response includes `count`, `permits[]`, `source_label`, `data_freshness`, and `city`.

---

## Data Model

### CanonicalPermit

The contract between connectors and the scoring engine. Every connector normalizes its source data into this schema.

```
permit_id          string              # Unique ID from the source system
city               string              # "Los Angeles", "New York", "San Francisco"
state              string              # "CA", "NY"
jurisdiction       string              # "City of Los Angeles", etc.
permit_type        PermitType          # NEW_CONSTRUCTION | MAJOR_RENOVATION | ADDITION | DEMOLITION | OTHER
permit_status      PermitStatus        # SUBMITTED | UNDER_REVIEW | APPROVED | ISSUED | FINAL | EXPIRED
project_description string             # Free text from the permit application
address            string              # Project address
latitude           float | null        # Coordinates (not available in all datasets)
longitude          float | null
valuation          float | null        # Estimated project value in USD
occupancy_type     OccupancyType       # COMMERCIAL | RESIDENTIAL_MULTI | RESIDENTIAL_SINGLE | MIXED_USE | CIVIC | EDUCATIONAL | INDUSTRIAL | OTHER
applicant_name     string | null       # Person or company that filed the permit
owner_name         string | null       # Property owner (not available in all datasets)
filing_date        date                # Date the permit was submitted
approval_date      date | null         # Date the permit was approved/issued
data_source        string              # e.g., "LADBS/gwh9-jnip"
raw_data           dict                # Original unmodified source record
fetched_at         datetime            # When this record was retrieved
```

### ScoredPermit

Output of the scoring engine. Wraps `CanonicalPermit` with intelligence fields:

```
ordinance_triggered    bool             # Does a percent-for-art ordinance apply?
ordinance_dependent    bool             # Would removing the ordinance drop below current level?
ordinance_name         string | null    # Name of the triggered ordinance
art_budget_display     string           # Formatted range, e.g., "$80K-$120K"
budget_basis           string           # One-sentence derivation
relevance              "High" | "Medium" | "None"
relevance_reasons      string[]         # Human-readable scoring explanations
opportunity_stage      string           # Outreach timing: "Early", "Mid", "Late", "Act now"
keyword_signals        string[]         # High-signal keywords found in description
scoring_factors        string[]         # Machine-readable factor log for debugging
```

### Lead Data (leads.xlsx)

Leads are stored in an Excel workbook with separate sheets for Corporate and Public Sector:

```
Company Name | Type | Location | Geographic Area | Why They're a Lead |
Company Website | Source URL | Potential Contact | ICP Score |
Estimated Budget | Budget Basis | Budget Confidence | Project Stage |
Notes | Date Found | Lead Source
```

Deep dive results append additional columns: Project Status, News Summary, Existing Art Attachments, Key Principals, Commissioning History, Deep Dive Date.

---

## Testing

```bash
# Run all tests (no API keys required — all external calls are mocked)
pytest                          # 275 tests
pytest -v                       # verbose output
pytest --cov                    # with coverage report
pytest tests/test_permits_engine.py   # engine tests only (110 tests)
pytest tests/test_permits_connector.py # connector tests (42 tests)
pytest tests/test_endpoints.py        # endpoint tests (59 tests)
```

### Test Organization

| File | Tests | Coverage |
|---|---|---|
| `test_permits_engine.py` | 110 | Scoring logic, typology detection, owner matching, ordinance matching (LA/NYC/SF), keyword scoring, sqft scoring, outreach timing, relevance reasons, budget formatting, `_fmt_k` |
| `test_endpoints.py` | 59 | Health check, leads endpoint (with geography filter), download, permits API (Socrata mocked), city params, sector filter, input validation, error isolation, reports CRUD, deep dive SSE, feedback POST/GET |
| `test_permits_connector.py` | 42 | LA/NYC/SF config validation, normalization, deduplication, error handling, where clause building, caching, field mapping |
| `test_permits_schema.py` | 18 | CanonicalPermit construction, enum mappings (LA permit types, statuses, occupancy), valuation parsing, connector metadata |
| `test_spreadsheet.py` | 9 | Headers, column mapping, date population, missing fields, duplicates, sheet creation, return values |

All tests use:
- Temporary `DATA_DIR` (no production file writes)
- Mocked Anthropic client (no real API calls)
- Mocked Socrata responses (no real data fetches)
- Real ordinance JSON (loaded from disk)

---

## Deployment

### Railway (Production)

The app auto-deploys from `main` on push. Configuration:

```
# Procfile
web: gunicorn app:app --bind 0.0.0.0:$PORT --timeout 300 --workers 1
```

Single worker is intentional — eliminates race conditions on `leads.xlsx` and `feedback.jsonl` file access. At current scale (single-digit concurrent users), this is the correct trade-off.

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes (for Lead Finder) | — | Anthropic API key for Claude access |
| `PORT` | No | `5000` | Server port (Railway sets this automatically) |
| `DATA_DIR` | No | `.` | Directory for `leads.xlsx`, `reports/`, `feedback.jsonl` |

### Local Development

```bash
# macOS: port 5000 conflicts with AirPlay Receiver
PORT=5001 python app.py
```

---

## Project Structure

```
first-agent/
├── app.py                              # Flask server, SSE streaming, agent loop
├── agent.py                            # Standalone CLI version of the lead finder
├── tools.py                            # Excel read/write, deduplication
├── prompts.py                          # System prompts for corporate/public sector
├── hello.py                            # API connectivity test
│
├── permits/                            # Art commissioning intelligence engine
│   ├── __init__.py                     # Public exports
│   ├── schema.py                       # CanonicalPermit dataclass + enums
│   ├── engine.py                       # Scoring engine (947 lines)
│   ├── routes.py                       # Flask blueprint (/api/permits, /api/feedback)
│   ├── connectors/
│   │   ├── base.py                     # Abstract connector interface
│   │   ├── socrata.py                  # Generic Socrata API client
│   │   └── cities/
│   │       ├── los_angeles.py          # LA config (LADBS datasets)
│   │       ├── new_york.py             # NYC config (DOB NOW Build datasets)
│   │       └── san_francisco.py        # SF config (DBI dataset)
│   ├── ordinances/
│   │   └── data/
│   │       └── percent_for_art.json    # Per-city ordinance data (5 entries, 3 cities)
│   └── scoring/
│       └── owner_patterns.json         # Developer, hotel, healthcare, transit patterns
│
├── templates/
│   ├── index.html                      # Lead Finder page
│   ├── permits.html                    # Opportunities page
│   ├── reports.html                    # Reports archive
│   └── report.html                     # Individual report view
│
├── tests/
│   ├── conftest.py                     # Shared fixtures (tmp dirs, mocks, make_permit)
│   ├── test_endpoints.py              
│   ├── test_permits_engine.py         
│   ├── test_permits_connector.py      
│   ├── test_permits_schema.py         
│   └── test_spreadsheet.py           
│
├── Procfile                            # Railway deployment config
├── requirements.txt                    # Python dependencies (pinned)
├── pyproject.toml                      # pytest and coverage config
├── CLAUDE.md                           # Claude Code operational instructions
├── PERMITS_PROJECT.md                  # Permits engine design document
└── .env.example                        # Environment variable template
```

---

## Configuration

### Scoring Thresholds (`permits/engine.py`)

All scoring constants are defined at the top of the file. To tune scoring behavior, modify these values:

```python
_HIGH_THRESHOLD = 6              # Minimum score for High relevance
_MEDIUM_THRESHOLD = 3            # Minimum score for Medium relevance
_VALUATION_NONE_FLOOR = 2_000_000    # Below this, no relevance regardless of score
_VALUATION_HOTEL_HIGH_FLOOR = 15_000_000
_VALUATION_HEALTHCARE_HIGH_FLOOR = 20_000_000
# ... (see engine.py for full list)
```

### Owner Patterns (`permits/scoring/owner_patterns.json`)

Add new developer, hotel brand, healthcare system, or transit authority patterns by editing this JSON file. No code changes required. Patterns are case-insensitive substring matches.

### Ordinance Data (`permits/ordinances/data/percent_for_art.json`)

Add new city ordinances by appending entries to this file. Required fields: `city`, `state`, `ordinance_name`, `percentage`, `project_types`, `practical_strength`. The engine will automatically pick up new entries for matching cities.

---

## Contributing a New City

Adding a Socrata-powered city requires four steps:

### 1. Identify the Dataset

```bash
# Fetch a sample row to discover field names
curl -s "https://<domain>/resource/<dataset-id>.json?$limit=1" | python3 -m json.tool

# Get distinct values for key fields
curl -s "https://<domain>/resource/<dataset-id>.json?$select=<field>,count(*)%20as%20cnt&$group=<field>&$order=cnt%20DESC&$limit=20"
```

### 2. Create the City Config

Create `permits/connectors/cities/<city_name>.py`:

```python
from permits.connectors.socrata import SocrataConnector, SocrataConfig, SocrataDataset

CITY_CONFIG = SocrataConfig(
    city="City Name",
    state="ST",
    jurisdiction="City of ...",
    socrata_domain="data.example.org",
    datasets={
        "submitted": SocrataDataset(id="xxxx-xxxx", name="...", role="submitted",
                                     primary_sort_field="filed_date", has_coordinates=True),
        "issued":    SocrataDataset(id="yyyy-yyyy", name="...", role="issued",
                                     primary_sort_field="issued_date", has_coordinates=True),
    },
    permit_type_field="...",
    status_field="...",
    occupancy_type_field="...",
    valuation_field="...",
    field_map={ ... },              # Map canonical field names to source field names
    permit_type_map={ ... },        # Map source permit types to canonical enums
    permit_status_map={ ... },      # Map source statuses to canonical enums
    occupancy_type_map={ ... },     # Map source occupancy types to canonical enums
    default_permit_types=[...],
)

city_connector = SocrataConnector(CITY_CONFIG)
```

### 3. Register the Connector

Add imports to:
- `permits/connectors/__init__.py`
- `permits/__init__.py`
- `permits/routes.py` (add to `_CONNECTORS` and `_SOURCE_LABELS` dicts)

Add the city option to `templates/permits.html` (dropdown and `CITY_CONFIG` JS object).

### 4. Add Ordinance Data

If the city has a percent-for-art ordinance, add an entry to `permits/ordinances/data/percent_for_art.json`. Research the `practical_strength` — is the ordinance actively enforced, or do developers typically satisfy it through in-lieu fees?

### 5. Add Tests

Mirror the existing city test coverage in `tests/test_permits_connector.py` (config validation, field mapping) and `tests/test_permits_engine.py` (ordinance matching for the new city).

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| Flask | 3.1.3 | Web framework |
| gunicorn | 25.1.0 | Production WSGI server |
| anthropic | 0.84.0 | Claude API client (Lead Finder) |
| httpx | 0.28.1 | HTTP client for Socrata API calls |
| openpyxl | 3.1.5 | Excel spreadsheet read/write |
| python-dotenv | 1.2.2 | Environment variable loading |
| pydantic | 2.12.5 | Data validation (Anthropic SDK dependency) |

Dev dependencies: `pytest`, `pytest-cov`
