"""
Tests for the CanonicalPermit schema and the LA connector field/enum mappings.
These tests are purely in-memory — no Socrata API calls.
"""

import pytest
from datetime import date, datetime

from permits.schema import (
    CanonicalPermit, PermitType, PermitStatus, OccupancyType,
    PIPELINE_STATUSES, ISSUED_STATUSES,
)
from permits.connectors.cities.los_angeles import LA_CONFIG
from permits.connectors.socrata import SocrataConnector


# ── CanonicalPermit construction ───────────────────────────────────────────────

class TestCanonicalPermitConstruction:

    def test_construct_with_required_fields(self):
        p = CanonicalPermit(
            permit_id="23-123456",
            city="Los Angeles",
            state="CA",
            jurisdiction="City of Los Angeles",
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            project_description="New office building",
            address="100 Spring St, Los Angeles, CA",
            data_source="LADBS/gwh9-jnip",
            fetched_at=datetime(2026, 4, 12),
        )
        assert p.permit_id == "23-123456"
        assert p.city == "Los Angeles"
        assert p.state == "CA"
        assert p.jurisdiction == "City of Los Angeles"
        assert p.permit_type == PermitType.NEW_CONSTRUCTION
        assert p.permit_status == PermitStatus.UNDER_REVIEW

    def test_optional_fields_default_to_none_or_empty(self):
        p = CanonicalPermit(
            permit_id="X",
            city="LA", state="CA", jurisdiction="City of LA",
            permit_type=PermitType.OTHER,
            permit_status=PermitStatus.SUBMITTED,
            project_description="",
            address="",
            data_source="test",
            fetched_at=datetime.utcnow(),
        )
        assert p.valuation is None
        assert p.latitude is None
        assert p.longitude is None
        assert p.applicant_name is None
        assert p.owner_name is None
        assert p.filing_date is None
        assert p.approval_date is None
        assert p.raw_data == {}
        assert p.occupancy_type == OccupancyType.OTHER

    def test_raw_data_preserved_unmodified(self):
        original = {"permit_nbr": "X-1", "valuation": "9000000", "extra_field": "keep_me"}
        p = CanonicalPermit(
            permit_id="X-1",
            city="LA", state="CA", jurisdiction="J",
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            project_description="test",
            address="test",
            data_source="test",
            fetched_at=datetime.utcnow(),
            raw_data=original,
        )
        assert p.raw_data is original
        assert p.raw_data["extra_field"] == "keep_me"

    def test_to_dict_includes_expected_keys(self):
        p = CanonicalPermit(
            permit_id="T-1",
            city="Los Angeles", state="CA", jurisdiction="City of Los Angeles",
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            project_description="desc",
            address="addr",
            data_source="src",
            fetched_at=datetime(2026, 1, 1),
            valuation=5_000_000.0,
            raw_data={"cpa": "Downtown", "cd": "14"},
        )
        d = p.to_dict()
        assert d["permit_id"] == "T-1"
        assert d["permit_type"] == "NEW_CONSTRUCTION"
        assert d["permit_status"] == "UNDER_REVIEW"
        assert d["valuation_display"] == "$5,000,000"
        assert d["neighborhood"] == "Downtown"
        assert d["council_district"] == "14"

    def test_to_dict_valuation_display_none(self):
        p = CanonicalPermit(
            permit_id="T-2", city="LA", state="CA", jurisdiction="J",
            permit_type=PermitType.OTHER, permit_status=PermitStatus.SUBMITTED,
            project_description="", address="", data_source="src",
            fetched_at=datetime.utcnow(), valuation=None,
        )
        assert p.to_dict()["valuation_display"] == ""

    def test_pipeline_and_issued_status_sets(self):
        assert PermitStatus.UNDER_REVIEW in PIPELINE_STATUSES
        assert PermitStatus.APPROVED in PIPELINE_STATUSES
        assert PermitStatus.ISSUED in ISSUED_STATUSES
        assert PermitStatus.FINAL in ISSUED_STATUSES
        # Sanity: no overlap
        assert PIPELINE_STATUSES.isdisjoint(ISSUED_STATUSES)


# ── LA permit_type enum mapping ────────────────────────────────────────────────

class TestLAPermitTypeMapping:
    """Every mapping from PERMITS_PROJECT.md § permit_type enum mapping."""

    @pytest.mark.parametrize("source_value,expected_enum", [
        ("Bldg-New",          PermitType.NEW_CONSTRUCTION),
        ("Bldg-Alter/Repair", PermitType.MAJOR_RENOVATION),
        ("Bldg-Addition",     PermitType.ADDITION),
        ("Bldg-Demolition",   PermitType.DEMOLITION),
    ])
    def test_known_type_maps_correctly(self, source_value, expected_enum):
        mapped = LA_CONFIG.permit_type_map.get(source_value)
        assert mapped is not None, f"'{source_value}' not in permit_type_map"
        assert PermitType(mapped) == expected_enum

    def test_unknown_type_has_no_entry_defaults_to_other(self):
        """Unrecognised types are not in the map; normalizer falls back to OTHER."""
        assert "Plumbing-New" not in LA_CONFIG.permit_type_map
        # Verify the connector normalizer would produce OTHER
        connector = SocrataConnector(LA_CONFIG)
        dataset = LA_CONFIG.datasets["submitted"]
        row = {
            "permit_nbr": "UNKNOWN-001",
            "permit_type": "Plumbing-New",
            "status_desc": "Issued",
            "permit_sub_type": "Commercial",
            "valuation": "6000000",
            "work_desc": "test",
            "primary_address": "100 Main St",
            "submitted_date": "2026-01-01T00:00:00.000",
        }
        permit = connector._normalize(row, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.permit_type == PermitType.OTHER


# ── LA permit_status enum mapping ─────────────────────────────────────────────

class TestLAPermitStatusMapping:
    """Every status mapping from PERMITS_PROJECT.md § permit_status enum mapping."""

    @pytest.mark.parametrize("source_value,expected_enum", [
        # UNDER_REVIEW
        ("PC Info Complete",          PermitStatus.UNDER_REVIEW),
        ("Verifications in Progress", PermitStatus.UNDER_REVIEW),
        ("Corrections Issued",        PermitStatus.UNDER_REVIEW),
        # APPROVED
        ("Quality Review Completed",  PermitStatus.APPROVED),
        ("Reviewed by Supervisor",    PermitStatus.APPROVED),
        ("PC Approved",               PermitStatus.APPROVED),
        ("Ready to Issue",            PermitStatus.APPROVED),
        # ISSUED
        ("Issued",                    PermitStatus.ISSUED),
        ("CofO in Progress",          PermitStatus.ISSUED),
        # FINAL
        ("CofO Issued",               PermitStatus.FINAL),
        ("CofC Issued",               PermitStatus.FINAL),
        ("OK for CofC",               PermitStatus.FINAL),
        ("Permit Finaled",            PermitStatus.FINAL),
        # EXPIRED
        ("Permit Expired",            PermitStatus.EXPIRED),
        ("Permit Closed",             PermitStatus.EXPIRED),
        ("Refund in Progress",        PermitStatus.EXPIRED),
    ])
    def test_known_status_maps_correctly(self, source_value, expected_enum):
        mapped = LA_CONFIG.permit_status_map.get(source_value)
        assert mapped is not None, f"'{source_value}' not in permit_status_map"
        assert PermitStatus(mapped) == expected_enum

    def test_unknown_status_defaults_to_under_review_via_normalizer(self):
        """Unrecognised statuses default to UNDER_REVIEW (earliest-stage assumption)."""
        connector = SocrataConnector(LA_CONFIG)
        dataset = LA_CONFIG.datasets["submitted"]
        row = {
            "permit_nbr": "S-001",
            "permit_type": "Bldg-New",
            "status_desc": "Some Totally Unknown Status",
            "permit_sub_type": "Commercial",
            "valuation": "5000000",
            "work_desc": "test",
            "primary_address": "1 Main",
            "submitted_date": "2026-01-01T00:00:00.000",
        }
        permit = connector._normalize(row, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.permit_status == PermitStatus.UNDER_REVIEW


# ── LA occupancy_type enum mapping ────────────────────────────────────────────

class TestLAOccupancyTypeMapping:
    """Every mapping from PERMITS_PROJECT.md § occupancy_type enum mapping."""

    @pytest.mark.parametrize("source_value,expected_enum", [
        ("Commercial",             OccupancyType.COMMERCIAL),
        ("Apartment",              OccupancyType.RESIDENTIAL_MULTI),
        ("1 or 2 Family Dwelling", OccupancyType.RESIDENTIAL_SINGLE),
        ("Office",                 OccupancyType.COMMERCIAL),
        ("Hotel",                  OccupancyType.COMMERCIAL),
        ("Industrial",             OccupancyType.INDUSTRIAL),
        ("School",                 OccupancyType.EDUCATIONAL),
        ("Hospital",               OccupancyType.CIVIC),
    ])
    def test_known_occupancy_maps_correctly(self, source_value, expected_enum):
        mapped = LA_CONFIG.occupancy_type_map.get(source_value)
        assert mapped is not None, f"'{source_value}' not in occupancy_type_map"
        assert OccupancyType(mapped) == expected_enum


# ── Valuation parsing ─────────────────────────────────────────────────────────

class TestValuationParsing:
    """Tests for SocrataConnector._parse_valuation."""

    @pytest.mark.parametrize("raw,expected", [
        ("5000000",       5_000_000.0),
        ("5518656.50",    5_518_656.50),
        ("  9000000  ",   9_000_000.0),   # whitespace stripped
        ("100000000.00",  100_000_000.0),
    ])
    def test_valid_strings_parse_correctly(self, raw, expected):
        result = SocrataConnector._parse_valuation(raw)
        assert result == pytest.approx(expected)

    @pytest.mark.parametrize("raw", ["", None, "N/A", "not a number", "$$$$"])
    def test_invalid_or_empty_returns_none(self, raw):
        assert SocrataConnector._parse_valuation(raw) is None

    def test_numeric_value_is_accepted(self):
        # Some rows might already have a float; should still parse
        assert SocrataConnector._parse_valuation(5_000_000) == 5_000_000.0


# ── LA connector metadata ──────────────────────────────────────────────────────

class TestLAConnectorMetadata:
    """Verify city, state, jurisdiction, and data_source are correct for LA."""

    def test_connector_has_both_dataset_ids(self):
        assert "gwh9-jnip" in {ds["id"] for ds in SocrataConnector(LA_CONFIG).get_metadata().datasets}
        assert "pi9x-tg5x" in {ds["id"] for ds in SocrataConnector(LA_CONFIG).get_metadata().datasets}

    def test_metadata_city_state(self):
        meta = SocrataConnector(LA_CONFIG).get_metadata()
        assert meta.city == "Los Angeles"
        assert meta.state == "CA"

    def test_normalized_permit_has_correct_city_state_source(self):
        connector = SocrataConnector(LA_CONFIG)
        dataset = LA_CONFIG.datasets["submitted"]
        row = {
            "permit_nbr": "DST-001",
            "permit_type": "Bldg-New",
            "status_desc": "PC Approved",
            "permit_sub_type": "Commercial",
            "valuation": "8000000",
            "work_desc": "Office tower",
            "primary_address": "200 Main St",
            "submitted_date": "2025-06-01T00:00:00.000",
        }
        permit = connector._normalize(row, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.city == "Los Angeles"
        assert permit.state == "CA"
        assert permit.jurisdiction == "City of Los Angeles"
        assert "gwh9-jnip" in permit.data_source

    def test_normalized_permit_filing_date_parsed(self):
        connector = SocrataConnector(LA_CONFIG)
        dataset = LA_CONFIG.datasets["submitted"]
        row = {
            "permit_nbr": "DATE-001",
            "permit_type": "Bldg-New",
            "status_desc": "Issued",
            "permit_sub_type": "Commercial",
            "valuation": "5000000",
            "work_desc": "test",
            "primary_address": "1 Addr",
            "submitted_date": "2025-03-15T00:00:00.000",
        }
        permit = connector._normalize(row, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.filing_date == date(2025, 3, 15)
