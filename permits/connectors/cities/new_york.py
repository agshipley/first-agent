"""
New York City connector configuration.

Uses two DOB NOW Build datasets:
  - w9ak-ipjd: DOB NOW Build Job Application Filings (submitted/early signal)
  - rbx6-tga4: DOB NOW Build Approved Permits (approved/issued with cost data)

This is a simplified v1 connector that avoids legacy NYC datasets and keeps
field mapping focused on the two chosen source tables.
"""

from permits.connectors.socrata import SocrataConfig, SocrataConnector, SocrataDataset

NYC_PUBLIC_SECTOR_OWNER_PATTERNS = [
    "DDC",
    "Department of Design and Construction",
    "DOE",
    "Department of Education",
    "DOT",
    "Department of Transportation",
    "Parks",
    "Department of Parks and Recreation",
    "NYCHA",
    "New York City Housing Authority",
    "SCA",
    "School Construction Authority",
    "MTA",
    "Metropolitan Transportation Authority",
    "DCAS",
    "Department of Citywide Administrative Services",
    "Health + Hospitals",
    "NYC Health + Hospitals",
    "HHC",
]

NYC_CONFIG = SocrataConfig(
    city="New York",
    state="NY",
    jurisdiction="City of New York",
    socrata_domain="data.cityofnewyork.us",

    datasets={
        "submitted": SocrataDataset(
            id="w9ak-ipjd",
            name="DOB NOW Build Job Application Filings",
            role="submitted",
            primary_sort_field="filing_date",
            has_coordinates=True,
        ),
        "issued": SocrataDataset(
            id="rbx6-tga4",
            name="DOB NOW Build Approved Permits",
            role="issued",
            primary_sort_field="issued_date",
            has_coordinates=True,
        ),
    },

    permit_type_field={"submitted": "job_type", "issued": "work_type"},
    status_field={"submitted": "filing_status", "issued": "permit_status"},
    occupancy_type_field="building_type",
    valuation_field={"submitted": "initial_cost", "issued": "estimated_job_costs"},

    field_map={
        "permit_id": "job_filing_number",
        "project_description": "job_description",
        "address": "address",
        "latitude": "latitude",
        "longitude": "longitude",
        "permit_type_raw": "job_type",
        "permit_status_raw": "filing_status",
        "occupancy_type_raw": "building_type",
        "filing_date": "filing_date",
        "approval_date": "approved_date",
        "applicant_name": "applicant_business_name",
        "owner_name": "owner_business_name",
    },

    permit_type_map={
        "New Building": "NEW_CONSTRUCTION",
        "ALT-CO - New Building with Existing Elements to Remain": "NEW_CONSTRUCTION",
        "Alteration": "MAJOR_RENOVATION",
        "Alteration CO": "MAJOR_RENOVATION",
        "Full Demolition": "DEMOLITION",
        "Demolition": "DEMOLITION",
        "No Work": "OTHER",
        "General Construction": "MAJOR_RENOVATION",
        "Plumbing": "OTHER",
        "Construction Fence": "OTHER",
        "Solar Tax": "OTHER",
    },

    permit_status_map={
        "LOC Issued": "APPROVED",
        "Permit Entire": "ISSUED",
        "Approved": "APPROVED",
        "Permit Issued": "ISSUED",
        "Signed-off": "ISSUED",
        "Renewal Permit Without Changes": "UNDER_REVIEW",
    },

    occupancy_type_map={
        "1-2-3 FAMILY": "RESIDENTIAL_MULTI",
        "3 Family": "RESIDENTIAL_MULTI",
        "2 Family": "RESIDENTIAL_MULTI",
        "1 Family": "RESIDENTIAL_SINGLE",
        "House": "RESIDENTIAL_SINGLE",
        "Office": "COMMERCIAL",
        "Hotel": "COMMERCIAL",
        "School": "EDUCATIONAL",
        "Hospital": "CIVIC",
        "Library": "CIVIC",
        "Government": "CIVIC",
        "Mixed Use": "MIXED_USE",
        "Other": "OTHER",
    },

    default_permit_types=[
        "New Building",
        "ALT-CO - New Building with Existing Elements to Remain",
        "Alteration",
        "Alteration CO",
    ],
    default_occupancy_types=[],

    public_sector_owner_patterns=NYC_PUBLIC_SECTOR_OWNER_PATTERNS,

    data_freshness="~daily (DOB NOW Build updates frequently)",
    known_limitations=[
        "Dataset field names differ between submitted and approved sources; the connector uses field-specific mapping and normalization fallback logic.",
        "Public-sector ordinance eligibility depends on matching owner/applicant names against known NYC agencies. Private developer records are not assumed to trigger the ordinance.",
        "Job application filings may lack a full narrative description; the connector falls back to available job/work fields where possible.",
    ],
)

nyc_connector = SocrataConnector(NYC_CONFIG)
