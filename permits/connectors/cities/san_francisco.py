"""
San Francisco building permit connector.

Data source: SF Department of Building Inspection (DBI) via data.sfgov.org
Dataset: p4e4-a5a7 (Building Permits — deduplicated, one row per permit)

Unlike LA and NYC which use separate submitted/issued datasets, SF uses a
single dataset with a `status` field. We key it as "all" and handle
status-based filtering in the where clause.
"""

from permits.connectors.socrata import SocrataConnector, SocrataConfig, SocrataDataset


SF_CONFIG = SocrataConfig(
    city="San Francisco",
    state="CA",
    jurisdiction="City and County of San Francisco",
    socrata_domain="data.sfgov.org",

    datasets={
        "submitted": SocrataDataset(
            id="p4e4-a5a7",
            name="Building Permits (Filed/Pipeline)",
            role="submitted",
            primary_sort_field="filed_date",
            has_coordinates=True,
        ),
        "issued": SocrataDataset(
            id="p4e4-a5a7",
            name="Building Permits (Issued/Complete)",
            role="issued",
            primary_sort_field="issued_date",
            has_coordinates=True,
        ),
    },

    permit_type_field="permit_type_definition",
    status_field="status",
    occupancy_type_field="proposed_use",
    valuation_field="estimated_cost",

    field_map={
        "permit_id": "permit_number",
        "project_description": "description",
        "address": "address",
        "latitude": "latitude",
        "longitude": "longitude",
        "permit_type_raw": "permit_type_definition",
        "permit_status_raw": "status",
        "occupancy_type_raw": "proposed_use",
        "filing_date": "filed_date",
        "approval_date": "issued_date",
    },

    permit_type_map={
        "new construction": "NEW_CONSTRUCTION",
        "new construction wood frame": "NEW_CONSTRUCTION",
        "additions alterations or repairs": "MAJOR_RENOVATION",
        "otc alterations permit": "MAJOR_RENOVATION",
        "demolitions": "DEMOLITION",
        "sign - erect": "OTHER",
        "wall or painted sign": "OTHER",
        "grade or quarry or fill or excavate": "OTHER",
    },

    permit_status_map={
        "filed": "UNDER_REVIEW",
        "filing": "UNDER_REVIEW",
        "triage": "UNDER_REVIEW",
        "plancheck": "UNDER_REVIEW",
        "approved": "APPROVED",
        "issued": "ISSUED",
        "complete": "FINAL",
        "reinstated": "ISSUED",
        "expired": "EXPIRED",
        "cancelled": "EXPIRED",
        "withdrawn": "EXPIRED",
        "suspend": "EXPIRED",
        "revoked": "EXPIRED",
        "disapproved": "EXPIRED",
        "denied": "EXPIRED",
        "incomplete": "UNDER_REVIEW",
        "appeal": "UNDER_REVIEW",
    },

    occupancy_type_map={
        "office": "COMMERCIAL",
        "retail sales": "COMMERCIAL",
        "food/beverage hndlng": "COMMERCIAL",
        "tourist hotel/motel": "COMMERCIAL",
        "residential hotel": "COMMERCIAL",
        "lending institution": "COMMERCIAL",
        "apartments": "RESIDENTIAL_MULTI",
        "2 family dwelling": "RESIDENTIAL_MULTI",
        "3 family dwelling": "RESIDENTIAL_MULTI",
        "1 family dwelling": "RESIDENTIAL_SINGLE",
        "warehouse,no frnitur": "INDUSTRIAL",
        "manufacturing": "INDUSTRIAL",
        "school": "EDUCATIONAL",
        "church": "CIVIC",
        "recreation bldg": "CIVIC",
        "theater": "CIVIC",
        "hospital": "CIVIC",
        "artist live/work": "MIXED_USE",
        "prkng garage/private": "INDUSTRIAL",
        "prkng garage/public": "INDUSTRIAL",
        "filling/service stn": "INDUSTRIAL",
        "auto repairs": "INDUSTRIAL",
    },

    default_permit_types=[
        "new construction",
        "new construction wood frame",
        "additions alterations or repairs",
    ],
    default_occupancy_types=[],

    public_sector_owner_patterns=[],

    data_freshness="~daily (SF DBI updates frequently)",
    known_limitations=[
        "Single dataset with status field — submitted and issued share the same source",
        "No owner/applicant name fields in dataset",
        "Occupancy uses 'proposed_use' free text — normalization may miss some categories",
        "Valuation stored as text — numeric $where filtering not supported",
    ],
)

sf_connector = SocrataConnector(SF_CONFIG)
