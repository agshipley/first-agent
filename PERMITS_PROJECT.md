# Permits Intelligence Project

## Source of Truth — Art Commissioning Opportunity Engine

**Project home:** `first-agent/permits/`
**Parent repo:** `github.com/agshipley/first-agent` (private)
**Status:** LA, NYC, and SF connectors live. Typology-primary scoring engine (v2) deployed.
**Last updated:** April 20, 2026

---

## Thesis

Building permit data is public. Access to it is the problem.

Municipal governments across the United States publish building permit applications, approvals, and inspection records. This data represents the earliest signal of construction activity — months to years before groundbreaking, press coverage, or project completion. For anyone who sells products or services into the construction lifecycle, permit data is the most valuable lead source that exists.

The problem is fragmentation. There are over 20,000 permitting jurisdictions in the US. They use different software platforms, different data schemas, different update cadences, and different levels of digital accessibility. Some publish structured data through modern APIs. Some post PDFs to municipal websites. Some require in-person records requests.

Several companies have built businesses around aggregating this data (see Competitive Landscape below). All of them serve the construction supply chain — contractors, subcontractors, building product manufacturers, real estate investors. None of them serve the creative sector.

This project builds an open-source intelligence layer that takes permit data and answers a question nobody else is asking: **which of these projects will commission art?**

The art commissioning market is underserved by tooling. Creative studios that curate and commission art for corporate and public spaces — like Tre Borden /Co, the studio this project was originally built for — find leads through word of mouth, manual RFP monitoring, and personal relationships. There is no systematic way for an artist or creative studio to see what's being built, assess whether it will involve art, and reach the right people early enough to influence the outcome.

This project changes that.

---

## Strategy

### Build in the open

The intelligence layer — the part that scores permits for art commissioning relevance — will be open source. Artists and creative studios will be able to use it for free. This is a deliberate choice:

- The creative community that benefits from this tool cannot afford $599/month data subscriptions.
- Open sourcing builds credibility and community faster than a paid product at this stage.
- The novel value is the intelligence layer, not the data plumbing. Open sourcing the intelligence layer does not give away a competitive advantage in data aggregation.

### Data source agnostic

The system is designed with a connector architecture so it can ingest permit data from any source:

- Free municipal open data APIs (Socrata, CKAN, custom portals)
- Commercial data providers (Shovels.ai, ATTOM, ConstructConnect)
- Manual data entry or CSV upload

Ship with free connectors for cities that publish open data. Make it pluggable so anyone can connect a commercial data source or contribute a new city connector.

### Start with LA, prove the model, expand

Los Angeles is the proof of concept. Tre Borden /Co operates here. LA has a Socrata-powered open data portal with building permit data accessible via API. LA has a percent-for-art ordinance (the Private Arts Development Fee Program administered by the Department of Cultural Affairs). The market dynamics are understood.

Once the LA connector and intelligence engine are validated, expand to other cities with strong open data portals (NYC, Chicago, San Francisco, Seattle, Portland) before tackling cities with less accessible data.

### Show Shovels what a vertical looks like

Shovels.ai has raised $5M to solve the permit data aggregation problem at national scale using AI. They cover 1,800+ jurisdictions and 85% of the US population. Their CEO has stated publicly that the data can be used "in myriad ways across multiple sectors."

This project is a working proof of that thesis — a vertical application built on permit data that serves a sector Shovels hasn't touched. The long-term play is a conversation: partnership, integration, or acquisition of the intelligence layer into their platform.

---

## Competitive Landscape

### Enterprise incumbents

| Company | Coverage | Pricing | Primary customers |
|---|---|---|---|
| Dodge Construction Network | 750,000+ projects/year | $6,000–$12,000/year per seat | GCs, architects, manufacturers |
| ConstructConnect | 500,000+ projects | $4,800–$8,400/year per seat | Subcontractors, estimators |
| Construction Monitor | Thousands of municipalities | Subscription-based | Contractors, suppliers |
| ATTOM Data | 158M+ properties nationwide | Enterprise/API pricing | Real estate, insurance, fintech |

These companies rely on human researcher networks (phone banks calling architects and municipal contacts) combined with public data scraping. Their data moats are relational, not purely technical. They serve the construction supply chain exclusively.

### AI-native challenger

| Company | Coverage | Pricing | Primary customers |
|---|---|---|---|
| Shovels.ai | 1,800+ jurisdictions, 85% US population | $599/month (web app or API) | Climate tech, proptech, contractors |

Shovels is the most relevant comparison. Founded 2022, $5M seed round (2025). They use AI to scrape, normalize, and enrich fragmented permit data. They also offer pre-permit intelligence from city council meetings and planning board discussions. Their data updates monthly on the 1st and 15th.

### Gap in the market

**No existing product serves the creative sector.** Every player above is oriented toward the construction supply chain — who's building, so I can sell materials, bid on subcontracting work, or invest in real estate. The question "which projects will commission art?" is not asked by any existing product.

This gap exists because the art commissioning market is too small to attract venture-scale attention. A tool serving this market would never justify the $5M+ investment required to build national-scale permit data infrastructure from scratch. But a tool that *layers intelligence on top of existing permit data* — whether from open APIs or commercial providers — can serve this market at a fraction of that cost.

---

## Architecture

### Relationship to first-agent

This project lives inside the `first-agent` repository as the `permits/` directory. It shares Flask and Railway deployment infrastructure with Tre's lead generation tool. It shares no application code with the lead gen tool — no imports between `permits/` and `app.py`/`tools.py`/`prompts.py`.

The lead generation tool (the rest of first-agent) is a client application. It uses the Anthropic API with web search to find and evaluate leads. The permits intelligence engine is a data processing layer. It ingests structured permit data from municipal APIs and applies art commissioning relevance scoring. They serve the same user (Tre's team) but through different mechanisms.

When this project outgrows the first-agent repo, it can be extracted cleanly because the `permits/` directory is self-contained.

### Directory structure

```
first-agent/
├── app.py                          # Lead gen tool (existing, do not modify)
├── tools.py                        # Lead gen tools (existing, do not modify)
├── prompts.py                      # Lead gen prompts (existing, do not modify)
├── permits/                        # Art commissioning intelligence engine
│   ├── __init__.py
│   ├── engine.py                   # Intelligence layer — relevance scoring, budget estimation
│   ├── schema.py                   # Canonical permit data model
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract connector interface
│   │   ├── socrata.py              # Generic Socrata API connector
│   │   └── cities/
│   │       ├── __init__.py
│   │       ├── los_angeles.py      # LA-specific dataset IDs, field mappings
│   │       ├── new_york.py         # NYC DOB NOW Build config (live)
│   │       ├── san_francisco.py    # SF DBI config (live)
│   │       └── ...
│   ├── ordinances/
│   │   ├── __init__.py
│   │   └── data/
│   │       ├── percent_for_art.json    # Per-city ordinance data
│   │       └── README.md               # How to contribute ordinance data
│   ├── scoring/
│   │   └── owner_patterns.json        # Developer, hotel brand, tech, cultural patterns
│   └── routes.py                   # Flask routes for the permits tab
├── templates/
├── static/
├── CLAUDE.md                       # Claude Code operational instructions
└── PERMITS_PROJECT.md              # This file — project source of truth
```

### Two-piece design

**Piece 1 — Intelligence engine (the novel thing)**

Takes normalized permit data and applies art commissioning relevance analysis:

- **Percent-for-art matching.** Does this project's jurisdiction have a percent-for-art ordinance? Does this permit's valuation and project type trigger the ordinance? What is the likely art budget based on the ordinance percentage and project value?
- **Project type scoring.** Commercial office, mixed-use residential, civic/municipal, transit infrastructure, and educational facilities are high-relevance project types. Single-family residential, minor renovations, and industrial facilities are low-relevance.
- **Budget estimation.** Even without a percent-for-art ordinance, estimates a likely art commissioning budget based on project valuation, project type, and comparable projects in the same market. Expressed as a range with a confidence level.
- **Timing assessment.** Where is this project in the development lifecycle? Permit application (earliest signal) → permit issued → construction start → near completion. Earlier is more valuable for art commissioning outreach.
- **Decision-maker inference.** Based on project type and jurisdiction, who is typically responsible for art commissioning decisions? Developer's design team, city arts commission, project architect, property management company.

**Piece 2 — Data connectors (modular, pluggable)**

Each connector knows how to fetch permit data from a specific source and map it into the canonical schema. Connectors are independent — adding a new city does not require modifying the engine or any other connector.

A connector must implement:
- `fetch(filters) → list[CanonicalPermit]` — fetch permits matching filter criteria
- `get_metadata() → ConnectorMetadata` — report what city/jurisdiction it covers, data freshness, available filter fields

The generic Socrata connector handles any Socrata-powered open data portal. City-specific configuration files provide the dataset IDs, field name mappings, and any city-specific filter logic.

For non-Socrata cities, custom connectors can be built that implement the same interface. The engine doesn't know or care where the data came from.

### Canonical permit schema

This is the contract between connectors and the engine. Every connector normalizes its source data into this schema. The engine only reads this schema.

```
CanonicalPermit:
  permit_id: string              # Unique identifier (source-specific)
  city: string                   # Standardized city name
  state: string                  # Two-letter state code
  jurisdiction: string           # Issuing jurisdiction name
  permit_type: enum              # NEW_CONSTRUCTION | MAJOR_RENOVATION | ADDITION | DEMOLITION | OTHER
  permit_status: enum            # SUBMITTED | UNDER_REVIEW | APPROVED | ISSUED | FINAL | EXPIRED
  project_description: string    # Free text description from the permit
  address: string                # Project address
  latitude: float | null         # Coordinates if available
  longitude: float | null
  valuation: float | null        # Estimated project value in USD
  occupancy_type: enum           # COMMERCIAL | RESIDENTIAL_MULTI | RESIDENTIAL_SINGLE | MIXED_USE | CIVIC | EDUCATIONAL | INDUSTRIAL | OTHER
  applicant_name: string | null  # Person or company that filed the permit
  owner_name: string | null      # Property owner if available
  filing_date: date              # Date the permit was submitted
  approval_date: date | null     # Date the permit was approved/issued
  data_source: string            # Which connector provided this record
  raw_data: dict                 # Original unmodified record from the source
  fetched_at: datetime           # When this record was retrieved
```

### Scoring Philosophy (v2)

The scoring engine was rewritten in April 2026 to shift from ordinance-primary to typology-primary scoring, based on research showing that weak ordinances (LA PADFP, SF Section 429) are poor predictors of actual art commissioning.

**Signal hierarchy (strongest to weakest):**

1. **Typology** — Hotels (+3), cultural/educational/civic (+2), mixed-use/commercial (+1). Hotels almost always include art programs regardless of ordinance. Industrial, warehouse, single-family, self-storage are hard-capped at None.
2. **Owner type** — Major developers (+2), hotel brands (+2), public-sector agencies (+2), tech companies (+1), cultural institutions (+1). Patterns stored in `permits/scoring/owner_patterns.json` — configurable without code changes.
3. **Keywords** — High-signal (lobby, plaza, atrium, museum, etc.) +1 each capped at +3. Low-signal (warehouse, parking, tenant improvement, etc.) -2 each uncapped.
4. **Ordinance** — Strong ordinances (LA Public Works, NYC DCLA, SF Art Enrichment) +2 with clear language. Weak ordinances (PADFP, Section 429) +1 with softer language noting historical underutilization.
5. **Valuation** — $50M+ landmark tier +2, $20M+ large +1. Hard floor at $2M (below = None).

**Valuation floors by typology:**
- General commercial: $25M for High
- Hotels and cultural: $15M for High
- Strong-ordinance public sector: $5M for High
- Landmark tier ($50M+): auto-qualifies for High consideration

**Score thresholds:** HIGH >= 6, MEDIUM >= 3, else NONE.

**Art budget calculation:**
- Strong ordinance: derives from actual ordinance rate (1% or 2%)
- Weak ordinance: uses heuristic (0.5%–1% of valuation, "actual commissioning varies")
- No ordinance: uses heuristic (0.5%–1.5% of valuation)

### Percent-for-art ordinance data model

```
Ordinance:
  city: string
  state: string
  ordinance_name: string                  # Official name of the program
  administering_body: string              # e.g., "Department of Cultural Affairs"
  percentage: float                       # e.g., 0.01 for 1%
  applies_to: enum[]                      # PRIVATE_DEVELOPMENT | PUBLIC_CAPITAL_PROJECTS | BOTH
  valuation_threshold: float | null       # Minimum project value to trigger (e.g., $500,000)
  project_types: string[]                 # Which project types trigger the ordinance
  in_lieu_fee_option: boolean             # Can developers pay a fee instead of commissioning art?
  in_lieu_fee_percentage: float | null    # If yes, what percentage?
  source_url: string                      # Link to the ordinance text or program page
  notes: string                           # Any relevant context
  last_verified: date                     # When this data was last confirmed accurate
```

This data is maintained as a JSON file and updated manually. Ordinances change infrequently. Accuracy matters more than automation here — a wrong ordinance percentage produces wrong budget estimates. Each entry should include a source URL so it can be verified.

---

## City Expansion Roadmap

### Priority cities and known data availability

| City | Open data portal | Platform | Percent-for-art | Priority | Status |
|---|---|---|---|---|---|
| Los Angeles | data.lacity.org | Socrata | Yes (PADFP) | 1 | Live — connector, ordinance, engine implemented |
| New York | data.cityofnewyork.us | Socrata | Yes (NYCDCC) | 2 | Live — connector, ordinance, sector filter implemented |
| San Francisco | data.sfgov.org | Socrata | Yes (2% Art Enrichment + Section 429) | 3 | Live — connector, two ordinances, sector filter |
| Chicago | data.cityofchicago.org | Socrata | Yes | 4 | Not started |
| Seattle | data.seattle.gov | Socrata | Yes | 5 | Not started |
| Portland | TBD | TBD | Yes | 6 | Not started |
| Washington D.C. | opendata.dc.gov | Socrata | Yes (DC Commission on the Arts) | 7 | Not started |
| Boston | data.boston.gov | Socrata | Partial | 8 | Not started |
| Dallas | dallasopendata.com | Socrata | TBD | 9 | Not started |
| Houston | TBD | TBD | No municipal ordinance | 10 | Not started |
| New Orleans | data.nola.gov | Socrata | TBD | 11 | Not started |

Note: "TBD" entries require research to confirm platform and ordinance status. Houston's lack of a percent-for-art ordinance doesn't mean there are no art commissioning opportunities — corporate developers may commission art voluntarily, and county or state programs may apply. The intelligence engine should handle cities without ordinances by applying general market heuristics.

Many of these cities appear to use Socrata. If confirmed, the generic Socrata connector can be reused with only city-specific configuration files. This is the scaling advantage of the connector architecture.

### Expansion strategy

1. Validate the full pipeline (connector → engine → UI) with Los Angeles.
2. Confirm Socrata availability for the next 4–5 cities. For each, the work is: identify the dataset ID, fetch a sample to discover field names, write a city config file mapping fields to the canonical schema, and research the local percent-for-art ordinance.
3. For cities without Socrata or accessible open data, evaluate whether the data gap can be filled by the lead gen tool's web search (the existing approach) rather than a direct data connector.

---

## Relationship to the Lead Generation Tool

The permits intelligence engine and the lead generation tool serve the same user but answer different questions:

| | Lead generation tool | Permits intelligence engine |
|---|---|---|
| **Question** | Who should Tre reach out to? | What's being built that might need art? |
| **Data source** | Open web via Anthropic API + web_search | Structured municipal permit data via APIs |
| **Method** | AI-driven search and evaluation | Data retrieval + programmatic scoring |
| **Signal timing** | Varies (news, RFPs, announcements) | Earliest possible (permit application filed) |
| **Cost per query** | Anthropic API tokens + web search fees | Free (open data APIs) or data subscription |
| **Output** | Scored leads with outreach context | Permit records with art commissioning relevance |

The two tools are complementary. A typical workflow:

1. The permits engine surfaces a new $50M mixed-use development permit in LA.
2. The engine scores it: triggers percent-for-art, estimated art budget $250K–$500K, high relevance.
3. The user clicks "Deep Dive" or "Send to Lead Search," which hands the project to the lead gen tool.
4. The lead gen tool uses web search to find the developer, the architect, recent news, existing art attachments, and key principals.
5. The user has a complete picture: structured permit data + web-enriched context.

The bridge between the two tools is the "Send to Lead Search" button on permit results, which pre-populates the lead gen search with the permit's project details.

---

## Open Source Plan

### What gets open sourced

- The intelligence engine (`engine.py`, `schema.py`)
- All data connectors (`connectors/`)
- The percent-for-art ordinance dataset (`ordinances/`)
- Documentation for adding new cities and contributing ordinance data

### What stays proprietary (for now)

- Tre Borden /Co's specific ICP rubric and system prompts (these are competitive intelligence for Tre's business)
- The lead generation tool (app.py, tools.py, prompts.py) — this is Tre's product

### License

TBD. Likely MIT or Apache 2.0 to maximize adoption. Decision deferred until closer to public release.

### Community contribution model

The most valuable community contributions are:
1. New city connector configurations (dataset IDs, field mappings)
2. Percent-for-art ordinance data for new jurisdictions
3. Bug reports and data quality issues

The project should make these contributions as easy as possible — a city config file is a JSON file with a handful of fields, not a complex engineering task. An artist in Portland who knows their local ordinance can contribute that knowledge without writing code.

---

## Los Angeles Connector Specification

This section is the source of truth for the LA connector implementation. Update it before and after any changes to `permits/connectors/cities/los_angeles.py`.

### Datasets

| Role | Dataset ID | Name | Refresh cadence | Primary sort key |
|---|---|---|---|---|
| **Primary** | `gwh9-jnip` | Building and Safety - Building Permits Submitted from 2020 to Present (N) | ~weekly (last: 2026-04-06) | `submitted_date DESC` |
| **Secondary** | `pi9x-tg5x` | Building and Safety - Building Permits Issued from 2020 to Present (N) | ~weekly (last: 2026-04-06) | `issue_date DESC` |

`gwh9-jnip` is the primary source because it captures permits earlier in the lifecycle — from the moment of submission, months before a permit is issued. `pi9x-tg5x` is secondary: it contains lat/lon coordinates (which `gwh9-jnip` does not) and serves as a source of supplemental data or for use cases where "permit issued" is the relevant trigger.

The connector must be able to query either dataset independently, or both with results merged and deduplicated on `permit_nbr`.

### Field mapping: source → CanonicalPermit

Both datasets share the same field names. Differences are noted.

| CanonicalPermit field | Source field | Dataset | Notes |
|---|---|---|---|
| `permit_id` | `permit_nbr` | both | |
| `city` | — | — | Hardcode `"Los Angeles"` |
| `state` | — | — | Hardcode `"CA"` |
| `jurisdiction` | — | — | Hardcode `"City of Los Angeles"` |
| `permit_type` | `permit_type` | both | See enum mapping below |
| `permit_status` | `status_desc` | both | See enum mapping below |
| `project_description` | `work_desc` | both | |
| `address` | `primary_address` | both | |
| `latitude` | `lat` | `pi9x-tg5x` only | **Not present in `gwh9-jnip`** — see Known Limitations |
| `longitude` | `lon` | `pi9x-tg5x` only | **Not present in `gwh9-jnip`** |
| `valuation` | `valuation` | both | Stored as text — see Valuation Parsing |
| `occupancy_type` | `permit_sub_type` | both | See enum mapping below |
| `applicant_name` | — | neither | Not available in either current dataset |
| `owner_name` | — | neither | Not available |
| `filing_date` | `submitted_date` | both | Always populated |
| `approval_date` | `issue_date` | both | Nullable in `gwh9-jnip` (permit not yet issued) |
| `data_source` | — | — | Set to `"LADBS/gwh9-jnip"` or `"LADBS/pi9x-tg5x"` |
| `raw_data` | *(full row dict)* | both | Pass through unmodified |
| `fetched_at` | — | — | Set at fetch time |

Additional fields available but outside the canonical schema (store in `raw_data`, surface in UI as needed): `zip_code`, `cd` (council district), `apc` (area planning commission), `cpa` (community plan area), `cnc` (neighborhood council), `use_code`, `use_desc`, `square_footage`, `height`, `construction`, `ev`, `solar`, `business_unit`, `cofo_date` (gwh9-jnip only).

### permit_type enum mapping

| Source value (`permit_type`) | CanonicalPermit enum |
|---|---|
| `Bldg-New` | `NEW_CONSTRUCTION` |
| `Bldg-Alter/Repair` | `MAJOR_RENOVATION` |
| `Bldg-Addition` | `ADDITION` |
| `Bldg-Demolition` | `DEMOLITION` |
| anything else | `OTHER` |

### permit_status enum mapping

| Source value (`status_desc`) | CanonicalPermit enum | Notes |
|---|---|---|
| `PC Info Complete` | `UNDER_REVIEW` | Plan check intake complete |
| `Verifications in Progress` | `UNDER_REVIEW` | Active plan check |
| `Corrections Issued` | `UNDER_REVIEW` | Awaiting applicant response |
| `Quality Review Completed` | `APPROVED` | Near end of plan check |
| `Reviewed by Supervisor` | `APPROVED` | Escalated but still approved track |
| `PC Approved` | `APPROVED` | Plan check approved |
| `Ready to Issue` | `APPROVED` | Fee payment pending — permit imminent |
| `Issued` | `ISSUED` | |
| `CofO in Progress` | `ISSUED` | Construction complete, occupancy pending |
| `CofO Issued` | `FINAL` | |
| `CofC Issued` | `FINAL` | Certificate of Compliance |
| `OK for CofC` | `FINAL` | |
| `Permit Finaled` | `FINAL` | |
| `Permit Expired` | `EXPIRED` | |
| `Permit Closed` | `EXPIRED` | |
| `Refund in Progress` | `EXPIRED` | |
| anything else | `UNDER_REVIEW` | Default to earliest-stage assumption |

**Note on `Ready to Issue`:** This status is particularly valuable for the intelligence engine — the permit is functionally approved and construction is imminent. The canonical `APPROVED` enum captures this correctly. If the engine later wants to distinguish "truly ready" from "under review," this can be refined without a schema change by filtering on the raw `status_desc` in `raw_data`.

### occupancy_type enum mapping

| Source value (`permit_sub_type`) | CanonicalPermit enum |
|---|---|
| `Commercial` | `COMMERCIAL` |
| `Apartment` | `RESIDENTIAL_MULTI` |
| `1 or 2 Family Dwelling` | `RESIDENTIAL_SINGLE` |
| `Office` | `COMMERCIAL` |
| `Hotel` | `COMMERCIAL` |
| `Industrial` | `INDUSTRIAL` |
| `School` | `EDUCATIONAL` |
| `Hospital` | `CIVIC` |
| anything else | `OTHER` |

Use `use_desc` as a fallback when `permit_sub_type` is absent or maps to `OTHER`.

### Valuation parsing

The `valuation` field is stored as **text** in both datasets. Rules:

1. Strip whitespace.
2. If empty or null → `valuation = None` in the canonical record.
3. Cast to `float`. If the cast fails (malformed string) → `valuation = None`.
4. Values may include decimal points (e.g., `"5518656.50"`) — float cast handles this correctly.
5. Store as `float` in the canonical schema. The UI layer is responsible for display formatting.

**Server-side pre-filtering:** Because `valuation` is text, Socrata's `$where valuation > N` numeric comparison will fail. Use `length(valuation) >= 7` as a server-side pre-filter (catches $1M+), then apply the exact numeric threshold in Python post-fetch. This is a known limitation of the LADBS dataset format.

### Known limitations

| Limitation | Affected dataset | Severity | Mitigation |
|---|---|---|---|
| No lat/lon coordinates | `gwh9-jnip` (submitted) | Medium | Coordinates available in `pi9x-tg5x` after permit issues. Forward geocoding from `primary_address` is a future enhancement. |
| No applicant/owner name | Both | High | Not present in either dataset. Cannot identify the developer from permit data alone. The "Send to Lead Search" flow hands the project address to the lead gen tool, which finds the developer via web search. |
| Valuation stored as text | Both | Low | Handled via length pre-filter + Python post-filter (documented above). |
| Pre-2020 data in separate datasets | — | Low | `b6ii-mhed` (before 2010) and `n3xg-rixm` (2010–2019) exist. Not needed for current use case. |

---

## Current Status and Next Steps

### Completed
- [x] Competitive landscape research
- [x] Architecture design (two-piece: engine + connectors)
- [x] Canonical schema definition
- [x] Ordinance data model definition
- [x] LA Socrata datasets identified — `gwh9-jnip` (submitted, primary) and `pi9x-tg5x` (issued, secondary)
- [x] LA submitted permits dataset confirmed — fields validated, pre-issuance records confirmed present
- [x] Status taxonomy mapped to canonical enum for both datasets
- [x] Valuation text-type limitation documented with workaround
- [x] Lat/lon limitation in submitted dataset documented
- [x] LA permits tab — basic implementation shipped (flat `permits.py` in root, needs refactor)
- [x] Refactor current LA permits code into the `permits/` directory structure
- [x] Build `permits/schema.py` — `CanonicalPermit` dataclass
- [x] Build `permits/connectors/base.py` — abstract connector interface
- [x] Build `permits/connectors/socrata.py` — generic Socrata fetching logic
- [x] Build `permits/connectors/cities/los_angeles.py` — LA config (dataset IDs, field mappings)
- [x] Build `permits/routes.py` — Flask blueprint
- [x] Update `app.py` to import blueprint from `permits/routes.py`
- [x] Add `gwh9-jnip` (submitted permits) to the UI
- [x] Build the intelligence engine — percent-for-art matching for LA (PADFP ordinance)
- [x] Populate `permits/ordinances/data/percent_for_art.json` with LA PADFP ordinance data
- [x] NYC DOB NOW Build connector (two datasets: submitted filings, approved permits)
- [x] NYC percent-for-art ordinance data (Public Art Allocation for Public Capital Projects)
- [x] City selector in routes and UI (los_angeles, new_york)
- [x] Project sector filter (all/public/private) replacing PADFP toggle
- [x] Public-sector owner pattern matching for NYC ordinance eligibility
- [x] Dynamic UI labels (city name, data source, freshness) per selected city

- [x] SF DBI connector (single dataset: p4e4-a5a7, status-based filtering)
- [x] SF percent-for-art ordinance data (2% Art Enrichment strong, Section 429 weak)
- [x] Scoring engine v2 — typology-primary, owner signals, softened ordinance weighting
- [x] Owner pattern matching from configurable JSON (permits/scoring/owner_patterns.json)
- [x] practical_strength field on ordinances (strong/weak)
- [x] scoring_factors field on ScoredPermit for debuggability

### In progress

*(Nothing currently in progress.)*

### Next
- [ ] Confirm Socrata availability for Chicago, Seattle
- [ ] Add connector configs for next 2–3 cities
- [ ] Update PERMITS_PROJECT.md expansion table as cities are confirmed

### Deferred
- [ ] Non-Socrata city connectors
- [ ] Commercial data source connectors (Shovels API, ATTOM)
- [ ] Geocoding for submitted permits (lat/lon not in `gwh9-jnip`)
- [ ] Open source release preparation (license, README, contribution guide)
- [ ] Shovels.ai outreach

---

## Principles

1. **The data is public. The access is the product.** We don't own permit data. We make it usable for people who've never heard of a Socrata API.

2. **Intelligence over plumbing.** The novel value is knowing which permits matter for art commissioning. The data ingestion is necessary but not differentiating. Don't over-invest in plumbing at the expense of intelligence.

3. **Accuracy over coverage.** A wrong percent-for-art percentage produces wrong budget estimates that erode trust. Better to cover 5 cities accurately than 50 cities with unverified data.

4. **Artists first.** Design decisions should be made from the perspective of someone who commissions or creates art for the built environment — not from the perspective of a contractor, developer, or investor. The UI, the language, the scoring criteria, and the output format should make sense to that person.

5. **Programmatic enforcement over prompt-based guidance.** Where a rule can be checked in code (does this valuation exceed the ordinance threshold?), check it in code. Don't rely on an LLM to apply the rule consistently. This principle carries forward from the first-agent project's core learning.
