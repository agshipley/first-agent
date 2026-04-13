"""
Tests for the Socrata connector and LA configuration.
All HTTP calls are mocked — no real Socrata requests.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock

from permits.schema import PermitType, PermitStatus, OccupancyType
from permits.connectors.base import ConnectorFilters
from permits.connectors.socrata import SocrataConnector, _cache
from permits.connectors.cities.los_angeles import LA_CONFIG, la_connector


# ── LA configuration ───────────────────────────────────────────────────────────

class TestLAConfiguration:

    def test_has_submitted_dataset(self):
        assert "submitted" in LA_CONFIG.datasets
        assert LA_CONFIG.datasets["submitted"].id == "gwh9-jnip"

    def test_has_issued_dataset(self):
        assert "issued" in LA_CONFIG.datasets
        assert LA_CONFIG.datasets["issued"].id == "pi9x-tg5x"

    def test_submitted_has_no_coordinates(self):
        assert LA_CONFIG.datasets["submitted"].has_coordinates is False

    def test_issued_has_coordinates(self):
        assert LA_CONFIG.datasets["issued"].has_coordinates is True

    def test_city_state_jurisdiction(self):
        assert LA_CONFIG.city == "Los Angeles"
        assert LA_CONFIG.state == "CA"
        assert LA_CONFIG.jurisdiction == "City of Los Angeles"

    def test_field_map_has_required_keys(self):
        required = {"permit_id", "project_description", "address", "filing_date"}
        for key in required:
            assert key in LA_CONFIG.field_map, f"field_map missing '{key}'"

    def test_default_permit_types_includes_new_and_alteration(self):
        assert "Bldg-New" in LA_CONFIG.default_permit_types
        assert "Bldg-Alter/Repair" in LA_CONFIG.default_permit_types


# ── Normalisation from fake API responses ─────────────────────────────────────

# A minimal raw row as Socrata would return for gwh9-jnip
SAMPLE_ROW = {
    "permit_nbr": "26-LA-12345",
    "permit_type": "Bldg-New",
    "status_desc": "Verifications in Progress",
    "permit_sub_type": "Commercial",
    "valuation": "8500000",
    "work_desc": "New 8-story office building",
    "primary_address": "500 Spring St, Los Angeles, CA 90013",
    "submitted_date": "2026-01-10T00:00:00.000",
    "issue_date": None,
    "zip_code": "90013",
    "cd": "14",
    "cpa": "Central City",
}


class TestNormalization:

    def _connector(self):
        return SocrataConnector(LA_CONFIG)

    def test_sample_row_normalises_to_canonical_permit(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["submitted"]
        permit = connector._normalize(SAMPLE_ROW, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.permit_id == "26-LA-12345"
        assert permit.city == "Los Angeles"
        assert permit.state == "CA"
        assert permit.permit_type == PermitType.NEW_CONSTRUCTION
        assert permit.permit_status == PermitStatus.UNDER_REVIEW
        assert permit.occupancy_type == OccupancyType.COMMERCIAL
        assert permit.valuation == pytest.approx(8_500_000.0)
        assert permit.address == "500 Spring St, Los Angeles, CA 90013"
        assert permit.filing_date is not None
        assert permit.approval_date is None  # not issued yet
        assert permit.raw_data is SAMPLE_ROW

    def test_row_without_permit_id_returns_none(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["submitted"]
        row = {**SAMPLE_ROW, "permit_nbr": ""}
        result = connector._normalize(row, dataset, datetime.utcnow())
        assert result is None

    def test_null_valuation_normalises_to_none(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["submitted"]
        row = {**SAMPLE_ROW, "valuation": None}
        permit = connector._normalize(row, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.valuation is None

    def test_issued_dataset_row_with_coordinates(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["issued"]
        row = {
            **SAMPLE_ROW,
            "lat": "34.0522",
            "lon": "-118.2437",
            "issue_date": "2026-03-01T00:00:00.000",
        }
        permit = connector._normalize(row, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.latitude == pytest.approx(34.0522)
        assert permit.longitude == pytest.approx(-118.2437)

    def test_submitted_dataset_has_no_coordinates(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["submitted"]
        row = {**SAMPLE_ROW, "lat": "34.0522", "lon": "-118.2437"}
        permit = connector._normalize(row, dataset, datetime.utcnow())
        assert permit is not None
        assert permit.latitude is None
        assert permit.longitude is None


# ── Deduplication ──────────────────────────────────────────────────────────────

class TestDeduplication:

    def test_duplicate_permit_ids_across_datasets_deduplicated(self):
        """When source='both', the same permit_nbr appearing in both datasets
        should only appear once in the result."""
        connector = SocrataConnector(LA_CONFIG)
        # Both rows have the same permit_nbr
        shared_row = {**SAMPLE_ROW, "permit_nbr": "SHARED-001"}

        with patch.object(connector, "_fetch_raw", side_effect=[
            [shared_row],   # submitted dataset
            [shared_row],   # issued dataset (same record)
        ]):
            filters = ConnectorFilters(
                min_valuation=0,
                permit_type="all",
                occupancy_type="all",
                status_category="pipeline",
                date_from="",
                limit=50,
                source="both",
            )
            results = connector.fetch(filters)

        permit_ids = [p.permit_id for p in results]
        assert permit_ids.count("SHARED-001") == 1

    def test_unique_permits_from_both_datasets_all_returned(self):
        connector = SocrataConnector(LA_CONFIG)
        row_a = {**SAMPLE_ROW, "permit_nbr": "AAA-001"}
        row_b = {**SAMPLE_ROW, "permit_nbr": "BBB-002"}

        with patch.object(connector, "_fetch_raw", side_effect=[
            [row_a],
            [row_b],
        ]):
            filters = ConnectorFilters(
                min_valuation=0, permit_type="all", occupancy_type="all",
                status_category="pipeline", date_from="", limit=50, source="both",
            )
            results = connector.fetch(filters)

        assert {p.permit_id for p in results} == {"AAA-001", "BBB-002"}


# ── Empty response handling ────────────────────────────────────────────────────

class TestEmptyResponse:

    def test_empty_api_response_returns_empty_list(self):
        connector = SocrataConnector(LA_CONFIG)
        with patch.object(connector, "_fetch_raw", return_value=[]):
            filters = ConnectorFilters(
                min_valuation=5_000_000, permit_type="all", occupancy_type="all",
                status_category="pipeline", date_from="", limit=50, source="submitted",
            )
            results = connector.fetch(filters)
        assert results == []


# ── Error handling ────────────────────────────────────────────────────────────

class TestErrorHandling:

    def test_http_500_raises_runtime_error(self):
        """A Socrata API 5xx should surface as RuntimeError, not crash silently."""
        connector = SocrataConnector(LA_CONFIG)
        import httpx

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=MagicMock(status_code=500),
        )

        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_ctx
            mock_ctx.get.return_value = mock_resp

            # Also clear cache so we actually hit the network path
            _cache.clear()

            filters = ConnectorFilters(
                min_valuation=5_000_000, permit_type="all", occupancy_type="all",
                status_category="pipeline", date_from="", limit=10, source="submitted",
            )
            with pytest.raises(RuntimeError, match="Socrata fetch error"):
                connector.fetch(filters)

    def test_timeout_raises_runtime_error(self):
        """A network timeout should surface as RuntimeError."""
        connector = SocrataConnector(LA_CONFIG)
        import httpx

        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_ctx
            mock_ctx.get.side_effect = httpx.TimeoutException("timeout")

            _cache.clear()

            filters = ConnectorFilters(
                min_valuation=5_000_000, permit_type="all", occupancy_type="all",
                status_category="pipeline", date_from="", limit=10, source="submitted",
            )
            with pytest.raises(RuntimeError, match="Socrata fetch error"):
                connector.fetch(filters)


# ── $where clause building ────────────────────────────────────────────────────

class TestWhereClause:

    def _connector(self):
        return SocrataConnector(LA_CONFIG)

    def test_valuation_prefilter_uses_length(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["submitted"]
        filters = ConnectorFilters(
            min_valuation=5_000_000, permit_type="all", occupancy_type="all",
            status_category="pipeline", date_from="", limit=50, source="submitted",
        )
        where = connector._build_where(dataset, filters)
        assert "length(valuation)" in where

    def test_pipeline_status_filter_included(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["submitted"]
        filters = ConnectorFilters(
            min_valuation=0, permit_type="all", occupancy_type="all",
            status_category="pipeline", date_from="", limit=50, source="submitted",
        )
        where = connector._build_where(dataset, filters)
        assert "status_desc" in where

    def test_date_from_included(self):
        connector = self._connector()
        dataset = LA_CONFIG.datasets["submitted"]
        filters = ConnectorFilters(
            min_valuation=0, permit_type="all", occupancy_type="all",
            status_category="pipeline", date_from="2025-01-01", limit=50, source="submitted",
        )
        where = connector._build_where(dataset, filters)
        assert "2025-01-01" in where
