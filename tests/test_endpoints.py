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
        """include_ordinance=false (back-compat): maps to sector=private, no dependent permits."""
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
        """Without include_ordinance param, default sector='all' shows everything."""
        rows = [self._mock_hotel_row(), self._mock_generic_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp_default = client.get(
                "/api/permits?source=submitted&min_valuation=5000000"
            )
            resp_all = client.get(
                "/api/permits?source=submitted&min_valuation=5000000&sector=all"
            )
        assert resp_default.get_json()["count"] == resp_all.get_json()["count"]

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


# ── City parameter tests ─────────────────────────────────────────────────────

class TestCityParameter:

    def _la_row(self):
        return {
            "permit_nbr": "LA-001",
            "permit_type": "Bldg-New",
            "status_desc": "Verifications in Progress",
            "permit_sub_type": "Commercial",
            "valuation": "10000000",
            "work_desc": "New hotel with lobby",
            "primary_address": "100 Spring St, Los Angeles",
            "submitted_date": "2026-01-01T00:00:00.000",
            "issue_date": None,
        }

    def _nyc_row(self):
        return {
            "job_filing_number": "NYC-001",
            "job_type": "New Building",
            "filing_status": "LOC Issued",
            "building_type": "Office",
            "initial_cost": "15000000",
            "job_description": "New office building with public art plaza",
            "house_no": "1",
            "street_name": "BROADWAY",
            "borough": "MANHATTAN",
            "zip": "10004",
            "owner_s_business_name": "Acme Development LLC",
            "latitude": "40.70",
            "longitude": "-74.01",
            "filing_date": "2026-02-01T00:00:00.000",
            "approved_date": None,
        }

    def test_default_city_is_los_angeles(self, client):
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[self._la_row()]):
            resp = client.get("/api/permits?source=submitted&min_valuation=5000000")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["city"] == "los_angeles"
        assert "LADBS" in data["source_label"]

    def test_explicit_los_angeles(self, client):
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[self._la_row()]):
            resp = client.get("/api/permits?city=los_angeles&source=submitted&min_valuation=5000000")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["city"] == "los_angeles"

    def test_new_york_returns_200(self, client):
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[self._nyc_row()]):
            resp = client.get("/api/permits?city=new_york&source=submitted&min_valuation=5000000")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["city"] == "new_york"
        assert "NYC DOB" in data["source_label"]

    def test_new_york_permits_have_scoring_fields(self, client):
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[self._nyc_row()]):
            resp = client.get("/api/permits?city=new_york&source=submitted&min_valuation=5000000")
        data = resp.get_json()
        if data["count"] > 0:
            p = data["permits"][0]
            assert "relevance" in p
            assert "ordinance_triggered" in p

    def test_unknown_city_returns_400(self, client):
        resp = client.get("/api/permits?city=chicago&source=submitted")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "chicago" in data["error"].lower()

    def test_metadata_default_is_los_angeles(self, client):
        resp = client.get("/api/permits/metadata")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["city"] == "Los Angeles"

    def test_metadata_new_york(self, client):
        resp = client.get("/api/permits/metadata?city=new_york")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["city"] == "New York"
        assert data["state"] == "NY"
        assert "NYC DOB" in data["source_label"]

    def test_metadata_unknown_city_returns_400(self, client):
        resp = client.get("/api/permits/metadata?city=boston")
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data


# ── Sector filter tests ─────────────────────────────────────────────────────���

class TestSectorFilter:

    def _la_commercial_row(self):
        return {
            "permit_nbr": "LA-PRIV-001",
            "permit_type": "Bldg-New",
            "status_desc": "Verifications in Progress",
            "permit_sub_type": "Commercial",
            "valuation": "10000000",
            "work_desc": "New hotel with lobby and gallery",
            "primary_address": "100 Main St",
            "submitted_date": "2026-01-01T00:00:00.000",
            "issue_date": None,
        }

    def test_sector_all_is_default(self, client):
        """sector=all shows everything High/Medium (same as no sector param)."""
        rows = [self._la_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp_default = client.get(
                "/api/permits?source=submitted&min_valuation=5000000"
            )
            resp_all = client.get(
                "/api/permits?source=submitted&min_valuation=5000000&sector=all"
            )
        assert resp_default.get_json()["count"] == resp_all.get_json()["count"]

    def test_sector_private_excludes_ordinance_dependent(self, client):
        """sector=private: ordinance-dependent permits excluded."""
        rows = [self._la_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp = client.get(
                "/api/permits?source=submitted&min_valuation=5000000&sector=private"
            )
        data = resp.get_json()
        for p in data["permits"]:
            assert p["ordinance_dependent"] is False

    def test_sector_private_strips_triggers_from_reasons(self, client):
        """sector=private: 'Triggers ...' reasons stripped."""
        rows = [self._la_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp = client.get(
                "/api/permits?source=submitted&min_valuation=5000000&sector=private"
            )
        data = resp.get_json()
        for p in data["permits"]:
            for reason in p.get("relevance_reasons", []):
                assert not reason.startswith("Triggers ")

    def test_sector_public_returns_200(self, client):
        """sector=public: returns 200 even if no public-sector permits match."""
        rows = [self._la_commercial_row()]
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=rows):
            resp = client.get(
                "/api/permits?source=submitted&min_valuation=5000000&sector=public"
            )
        assert resp.status_code == 200
        # LA rows have no owner data, so public sector filter returns 0
        assert resp.get_json()["count"] == 0


# ── Error isolation tests ────────────────────────────────────────────────────

class TestErrorIsolation:

    def _la_row(self):
        return {
            "permit_nbr": "LA-001",
            "permit_type": "Bldg-New",
            "status_desc": "Verifications in Progress",
            "permit_sub_type": "Commercial",
            "valuation": "10000000",
            "work_desc": "New hotel with lobby",
            "primary_address": "100 Spring St",
            "submitted_date": "2026-01-01T00:00:00.000",
            "issue_date": None,
        }

    def test_nyc_failure_does_not_break_la(self, client):
        """When NYC connector raises, LA should still work."""
        # First verify NYC fails gracefully
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   side_effect=RuntimeError("Socrata NYC is down")):
            resp_nyc = client.get(
                "/api/permits?city=new_york&source=submitted&min_valuation=5000000"
            )
        assert resp_nyc.status_code == 502
        data_nyc = resp_nyc.get_json()
        assert "error" in data_nyc

        # Then verify LA still works
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[self._la_row()]):
            resp_la = client.get(
                "/api/permits?city=los_angeles&source=submitted&min_valuation=5000000"
            )
        assert resp_la.status_code == 200
        assert resp_la.get_json()["count"] >= 0

    def test_la_failure_does_not_break_nyc(self, client):
        """When LA connector raises, NYC should still work."""
        nyc_row = {
            "job_filing_number": "NYC-001",
            "job_type": "New Building",
            "filing_status": "LOC Issued",
            "building_type": "Office",
            "initial_cost": "15000000",
            "job_description": "New office building",
            "house_no": "1",
            "street_name": "BROADWAY",
            "borough": "MANHATTAN",
            "zip": "10004",
            "latitude": "40.70",
            "longitude": "-74.01",
            "filing_date": "2026-02-01T00:00:00.000",
        }

        # First verify LA fails gracefully
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   side_effect=RuntimeError("Socrata LA is down")):
            resp_la = client.get(
                "/api/permits?city=los_angeles&source=submitted&min_valuation=5000000"
            )
        assert resp_la.status_code == 502

        # Then verify NYC still works
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   return_value=[nyc_row]):
            resp_nyc = client.get(
                "/api/permits?city=new_york&source=submitted&min_valuation=5000000"
            )
        assert resp_nyc.status_code == 200

    def test_connector_error_returns_user_friendly_message(self, client):
        """RuntimeError from connector should return 502 with error message."""
        with patch("permits.connectors.socrata.SocrataConnector._fetch_raw",
                   side_effect=RuntimeError("Connection timed out")):
            resp = client.get(
                "/api/permits?city=los_angeles&source=submitted&min_valuation=5000000"
            )
        assert resp.status_code == 502
        data = resp.get_json()
        assert "error" in data
        assert "timed out" in data["error"].lower()


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
