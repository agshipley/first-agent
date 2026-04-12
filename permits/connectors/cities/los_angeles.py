"""
Los Angeles connector configuration.

Implements the LA Connector Specification in PERMITS_PROJECT.md.
All dataset IDs, field mappings, and enum mappings come from that document —
do not change them here without updating the spec first.

Datasets:
  gwh9-jnip  Building Permits Submitted from 2020 to Present (N)  [PRIMARY]
  pi9x-tg5x  Building Permits Issued from 2020 to Present (N)     [SECONDARY]
"""

from permits.connectors.socrata import SocrataConfig, SocrataConnector, SocrataDataset

LA_CONFIG = SocrataConfig(
    city="Los Angeles",
    state="CA",
    jurisdiction="City of Los Angeles",
    socrata_domain="data.lacity.org",

    # ── Datasets ──────────────────────────────────────────────────────────────
    datasets={
        "submitted": SocrataDataset(
            id="gwh9-jnip",
            name="Building Permits Submitted from 2020 to Present",
            role="submitted",
            primary_sort_field="submitted_date",
            has_coordinates=False,   # Known limitation — no lat/lon in gwh9-jnip
        ),
        "issued": SocrataDataset(
            id="pi9x-tg5x",
            name="Building Permits Issued from 2020 to Present",
            role="issued",
            primary_sort_field="issue_date",
            has_coordinates=True,
        ),
    },

    # ── Source field names used in $where clauses ─────────────────────────────
    permit_type_field="permit_type",
    status_field="status_desc",
    occupancy_type_field="permit_sub_type",
    valuation_field="valuation",

    # ── Normalization field map: canonical_key → source_field_name ────────────
    field_map={
        "permit_id":          "permit_nbr",
        "project_description": "work_desc",
        "address":            "primary_address",
        "latitude":           "lat",
        "longitude":          "lon",
        "permit_type_raw":    "permit_type",
        "permit_status_raw":  "status_desc",
        "occupancy_type_raw": "permit_sub_type",
        "filing_date":        "submitted_date",
        "approval_date":      "issue_date",
    },

    # ── permit_type enum mapping ──────────────────────────────────────────────
    permit_type_map={
        "Bldg-New":           "NEW_CONSTRUCTION",
        "Bldg-Alter/Repair":  "MAJOR_RENOVATION",
        "Bldg-Addition":      "ADDITION",
        "Bldg-Demolition":    "DEMOLITION",
        # Default for unrecognized values: "OTHER" (applied in normalizer)
    },

    # ── permit_status enum mapping ────────────────────────────────────────────
    # Source: PERMITS_PROJECT.md — LA Connector Specification
    permit_status_map={
        # UNDER_REVIEW — active plan check
        "PC Info Complete":          "UNDER_REVIEW",
        "Verifications in Progress": "UNDER_REVIEW",
        "Corrections Issued":        "UNDER_REVIEW",
        # APPROVED — plan check approved, permit imminent
        "Quality Review Completed":  "APPROVED",
        "Reviewed by Supervisor":    "APPROVED",
        "PC Approved":               "APPROVED",
        "Ready to Issue":            "APPROVED",   # permit functionally approved; fee payment pending
        # ISSUED
        "Issued":                    "ISSUED",
        "CofO in Progress":          "ISSUED",
        # FINAL
        "CofO Issued":               "FINAL",
        "CofC Issued":               "FINAL",
        "OK for CofC":               "FINAL",
        "Permit Finaled":            "FINAL",
        # EXPIRED
        "Permit Expired":            "EXPIRED",
        "Permit Closed":             "EXPIRED",
        "Refund in Progress":        "EXPIRED",
        "CofO Corrected":            "FINAL",
        # Default for unrecognized values: "UNDER_REVIEW" (applied in normalizer)
    },

    # ── occupancy_type enum mapping ───────────────────────────────────────────
    occupancy_type_map={
        "Commercial":            "COMMERCIAL",
        "Apartment":             "RESIDENTIAL_MULTI",
        "1 or 2 Family Dwelling": "RESIDENTIAL_SINGLE",
        "Office":                "COMMERCIAL",
        "Hotel":                 "COMMERCIAL",
        "Industrial":            "INDUSTRIAL",
        "School":                "EDUCATIONAL",
        "Hospital":              "CIVIC",
        "Library":               "CIVIC",
        "Government":            "CIVIC",
        # Default for unrecognized: "OTHER" (applied in normalizer)
    },

    # ── Default filters when "all" is selected ────────────────────────────────
    # Restrict to project types that are plausible art commissioning candidates.
    # Single-family, grading, pools, and signage are excluded by default.
    default_permit_types=["Bldg-New", "Bldg-Alter/Repair", "Bldg-Addition"],
    default_occupancy_types=["Commercial", "Apartment"],

    # ── Metadata ──────────────────────────────────────────────────────────────
    data_freshness="~weekly (LADBS refreshes both datasets ~every 7 days)",
    known_limitations=[
        "No lat/lon in submitted permits dataset (gwh9-jnip) — coordinates only "
        "available after permit is issued (pi9x-tg5x). Geocoding from address is "
        "a future enhancement.",
        "No applicant or owner name in either dataset. Developer identification "
        "requires a separate web search step (via the lead gen tool).",
        "Valuation stored as text — numeric $where filtering not supported by "
        "Socrata for this dataset. Uses length() pre-filter + Python post-filter.",
    ],
)

# Singleton connector instance — import and use this directly.
la_connector = SocrataConnector(LA_CONFIG)
