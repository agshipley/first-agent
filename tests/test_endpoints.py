"""
Endpoint validation tests.

The Flask app is tested via test client with:
  - A temporary data directory (no real /data/ writes)
  - Anthropic API calls mocked (no real Claude calls)
  - Socrata API calls mocked where the permits routes would hit them

Some endpoints (deep-dive POST → SSE, /run → SSE) require the full Claude
agentic loop and are tested for basic request handling only — we verify the
response starts correctly without running the full loop.
"""

import json
import os
import uuid
import pytest
from unittest.mock import patch, MagicMock


# ── Health check ───────────────────────────────────────────────────────────────

class TestHealthEndpoint:

    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


# ── Download ───────────────────────────────────────────────────────────────────

class TestDownloadEndpoint:

    def test_download_404_when_no_spreadsheet(self, client):
        # Fresh tmp_data_dir — leads.xlsx does not exist yet
        resp = client.get("/download")
        assert resp.status_code == 404

    def test_download_200_with_correct_content_type(self, client, tmp_data_dir):
        # Create a minimal xlsx file so the route can serve it
        import openpyxl
        wb = openpyxl.Workbook()
        wb.save(tmp_data_dir / "leads.xlsx")

        resp = client.get("/download")
        assert resp.status_code == 200
        ct = resp.headers.get("Content-Type", "")
        assert "spreadsheetml" in ct or "openxmlformats" in ct


# ── Permits monitor page ───────────────────────────────────────────────────────

class TestPermitsMonitorEndpoint:

    def test_permits_monitor_returns_200(self, client):
        resp = client.get("/permits-monitor")
        assert resp.status_code == 200
        # Should render HTML
        assert b"LA Permits Monitor" in resp.data or b"permits" in resp.data.lower()


# ── /run endpoint ─────────────────────────────────────────────────────────────

class TestRunEndpoint:

    def test_run_without_segment_defaults_gracefully(self, client, mock_anthropic):
        """POST /run with no segment should not 500 — uses default 'corporate'."""
        # The SSE stream will start; we just check it doesn't immediately error
        # The mock_anthropic prevents real API calls
        mock_anthropic.messages.create.side_effect = Exception("Mock: no real API calls")

        resp = client.post("/run", data={})
        # Should return 200 streaming response (even if it errors mid-stream)
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/event-stream")


# ── /api/permits endpoint (mocked Socrata) ────────────────────────────────────

class TestApiPermitsEndpoint:

    def _mock_row(self):
        return {
            "permit_nbr": "TEST-001",
            "permit_type": "Bldg-New",
            "status_desc": "Verifications in Progress",
            "permit_sub_type": "Commercial",
            "valuation": "8000000",
            "work_desc": "New office tower",
            "primary_address": "100 Main St",
            "submitted_date": "2026-01-01T00:00:00.000",
            "issue_date": None,
        }

    def test_api_permits_returns_200_with_mocked_socrata(self, client):
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[self._mock_row()]):
            resp = client.get("/api/permits?source=submitted&min_valuation=5000000")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "permits" in data
        assert "count" in data

    def test_api_permits_response_includes_scoring_fields(self, client):
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[self._mock_row()]):
            resp = client.get("/api/permits?source=submitted&min_valuation=5000000")
        data = resp.get_json()
        assert data["count"] >= 1
        permit = data["permits"][0]
        assert "relevance" in permit
        assert "ordinance_triggered" in permit
        assert "ordinance_dependent" in permit
        assert "art_budget_display" in permit

    def _mock_hotel_row(self):
        return {
            "permit_nbr": "TEST-HOTEL-001",
            "permit_type": "Bldg-New",
            "status_desc": "Verifications in Progress",
            "permit_sub_type": "Commercial",
            "valuation": "10000000",
            "work_desc": "New hotel with lobby and rooftop gallery",
            "primary_address": "200 Hotel St",
            "submitted_date": "2026-01-01T00:00:00.000",
            "issue_date": None,
        }

    def _mock_generic_commercial_row(self):
        return {
            "permit_nbr": "TEST-OFFICE-001",
            "permit_type": "Bldg-New",
            "status_desc": "Verifications in Progress",
            "permit_sub_type": "Commercial",
            "valuation": "8000000",
            "work_desc": "New commercial office building",
            "primary_address": "300 Office Blvd",
            "submitted_date": "2026-01-01T00:00:00.000",
            "issue_date": None,
        }

    def test_include_ordinance_false_excludes_dependent_permits(self, client):
        """include_ordinance=false (default): only non-ordinance-dependent permits shown."""
        rows = [self._mock_hotel_row(), self._mock_generic_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp = client.get(
                "/api/permits?source=submitted&min_valuation=5000000"
                "&include_ordinance=false"
            )
        data = resp.get_json()
        for p in data["permits"]:
            assert p["ordinance_dependent"] is False, \
                f"Ordinance-dependent permit appeared with toggle OFF: {p['address']}"

    def test_include_ordinance_false_strips_padfp_from_reasons(self, client):
        """When PADFP toggle is OFF, 'Triggers ...' should not appear in reasons."""
        rows = [self._mock_hotel_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp = client.get(
                "/api/permits?source=submitted&min_valuation=5000000"
                "&include_ordinance=false"
            )
        data = resp.get_json()
        for p in data["permits"]:
            for reason in p.get("relevance_reasons", []):
                assert not reason.startswith("Triggers "), \
                    f"PADFP reason found with toggle OFF: {reason}"

    def test_include_ordinance_true_shows_all_permits(self, client):
        """include_ordinance=true: ordinance-dependent permits included."""
        rows = [self._mock_hotel_row(), self._mock_generic_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp = client.get(
                "/api/permits?source=submitted&min_valuation=5000000"
                "&include_ordinance=true"
            )
        data = resp.get_json()
        assert data["count"] >= 1

    def test_include_ordinance_default_is_false(self, client):
        """Without include_ordinance param, behavior should be same as false."""
        rows = [self._mock_hotel_row(), self._mock_generic_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp_default = client.get(
                "/api/permits?source=submitted&min_valuation=5000000"
            )
            resp_explicit = client.get(
                "/api/permits?source=submitted&min_valuation=5000000&include_ordinance=false"
            )
        assert resp_default.get_json()["count"] == resp_explicit.get_json()["count"]

    def test_api_permits_empty_response(self, client):
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[]):
            resp = client.get("/api/permits?source=submitted&min_valuation=5000000")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["count"] == 0
        assert data["permits"] == []

    def test_api_permits_metadata_returns_200(self, client):
        resp = client.get("/api/permits/metadata")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["city"] == "Los Angeles"
        assert data["state"] == "CA"


# ── /reports endpoints ────────────────────────────────────────────────────────

class TestReportsEndpoints:

    def test_list_reports_returns_json_array(self, client):
        resp = client.get("/api/reports")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_list_reports_with_existing_report(self, client, tmp_data_dir):
        report_id = str(uuid.uuid4())
        report = {
            "report_id": report_id,
            "company_name": "Test Corp",
            "geographic_area": "LA",
            "created_at": "2026-04-12T10:00:00+00:00",
            "lead_data": {},
            "report_sections": {},
        }
        reports_dir = tmp_data_dir / "reports"
        with open(reports_dir / f"{report_id}.json", "w") as f:
            json.dump(report, f)

        resp = client.get("/api/reports")
        data = resp.get_json()
        ids = [r["report_id"] for r in data]
        assert report_id in ids

    def test_get_nonexistent_report_returns_404(self, client):
        resp = client.get(f"/api/reports/{uuid.uuid4()}")
        assert resp.status_code == 404

    def test_get_existing_report_returns_200(self, client, tmp_data_dir):
        report_id = str(uuid.uuid4())
        report = {
            "report_id": report_id,
            "company_name": "Existing Corp",
            "geographic_area": "LA",
            "created_at": "2026-04-12T10:00:00+00:00",
            "lead_data": {},
            "report_sections": {},
        }
        reports_dir = tmp_data_dir / "reports"
        with open(reports_dir / f"{report_id}.json", "w") as f:
            json.dump(report, f)

        resp = client.get(f"/api/reports/{report_id}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["company_name"] == "Existing Corp"

    def test_get_report_path_traversal_blocked(self, client):
        """Report IDs with path components should return 404, not read arbitrary files."""
        resp = client.get("/api/reports/../../../etc/passwd")
        # Either 404 (report not found) or 400 — but never 200 with file contents
        assert resp.status_code in (404, 400, 308)


# ── /deep-dive/save endpoint ──────────────────────────────────────────────────

class TestDeepDiveSaveEndpoint:

    def test_save_without_report_id_returns_400(self, client):
        resp = client.post("/deep-dive/save",
                           data=json.dumps({}),
                           content_type="application/json")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_save_with_invalid_report_id_returns_404(self, client):
        resp = client.post("/deep-dive/save",
                           data=json.dumps({"report_id": "nonexistent-id"}),
                           content_type="application/json")
        assert resp.status_code == 404
        data = resp.get_json()
        assert "error" in data


# ── /deep-dive POST ───────────────────────────────────────────────────────────

class TestDeepDiveEndpoint:

    def test_deep_dive_with_valid_lead_starts_sse_stream(self, client, mock_anthropic):
        """POST /deep-dive should return a streaming response immediately."""
        mock_anthropic.messages.create.side_effect = Exception("Mock: no real API calls")

        lead = {
            "company_name": "Test Developer LLC",
            "type": "Real Estate",
            "location": "Los Angeles, CA",
        }
        resp = client.post("/deep-dive",
                           data=json.dumps(lead),
                           content_type="application/json")
        assert resp.status_code == 200
        assert resp.content_type.startswith("text/event-stream")
