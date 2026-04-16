"""
Shared fixtures for the first-agent test suite.

All external side-effects are isolated here:
  - Flask test client (app configured for testing)
  - Temporary directories for reports / spreadsheet output
  - Mock Anthropic client (tests never make real API calls)
  - Sample CanonicalPermit builders for permits engine tests
"""

import os
import json
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock, patch


# ── App / Flask client ─────────────────────────────────────────────────────────

@pytest.fixture
def tmp_data_dir(tmp_path):
    """
    Temporary DATA_DIR so tests never write to /data/.
    Sets the DATA_DIR env var for the duration of the test.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    reports_dir = data_dir / "reports"
    reports_dir.mkdir()

    original = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(data_dir)
    yield data_dir
    if original is None:
        del os.environ["DATA_DIR"]
    else:
        os.environ["DATA_DIR"] = original


@pytest.fixture
def app(tmp_data_dir):
    """
    Flask test application with an isolated data directory.
    Each test gets a clean state — no shared spreadsheet or reports.
    """
    # Import here so DATA_DIR is set before app initialises REPORTS_DIR
    import importlib
    import app as app_module
    importlib.reload(app_module)

    app_module.app.config["TESTING"] = True
    app_module.app.config["DATA_DIR"] = str(tmp_data_dir)
    yield app_module.app


@pytest.fixture
def client(app):
    """Flask test client."""
    with app.test_client() as c:
        yield c


# ── Spreadsheet isolation ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_leads_path(tmp_data_dir):
    """
    Returns the path where leads.xlsx would be written in this test's
    temporary data directory.  The file does not exist until code creates it.
    """
    return tmp_data_dir / "leads.xlsx"


# ── Mock Anthropic client ──────────────────────────────────────────────────────

class FakeTextBlock:
    """Minimal stand-in for an Anthropic ContentBlockText."""
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeToolUseBlock:
    """Minimal stand-in for an Anthropic ContentBlockToolUse."""
    def __init__(self, name, input_data, block_id="fake-tool-id"):
        self.type = "tool_use"
        self.name = name
        self.id = block_id
        self.input = input_data


class FakeResponse:
    """Minimal stand-in for an Anthropic Message response."""
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason


def make_save_leads_response(leads):
    """
    Helper: build a FakeResponse that looks like Claude calling
    save_leads_to_spreadsheet with the given leads list.
    """
    return FakeResponse(
        content=[FakeToolUseBlock(
            name="save_leads_to_spreadsheet",
            input_data={"leads": leads},
        )],
        stop_reason="tool_use",
    )


@pytest.fixture
def mock_anthropic():
    """
    Patches anthropic.Anthropic so no real API calls are made.
    Returns the mock client instance so tests can configure responses.

    Usage:
        mock_anthropic.messages.create.return_value = FakeResponse(...)
    """
    with patch("anthropic.Anthropic") as MockClass:
        mock_client = MagicMock()
        MockClass.return_value = mock_client
        yield mock_client


# ── Permits engine fixtures ────────────────────────────────────────────────────

from permits.schema import (
    CanonicalPermit, PermitType, PermitStatus, OccupancyType
)


def make_permit(
    permit_id="TEST-001",
    city="Los Angeles",
    state="CA",
    jurisdiction="City of Los Angeles",
    permit_type=PermitType.NEW_CONSTRUCTION,
    permit_status=PermitStatus.UNDER_REVIEW,
    occupancy_type=OccupancyType.COMMERCIAL,
    valuation=10_000_000.0,
    address="123 Test St, Los Angeles, CA",
    project_description="New commercial building",
    data_source="LADBS/gwh9-jnip",
    raw_data=None,
    filing_date=None,
    owner_name=None,
    applicant_name=None,
):
    """
    Build a CanonicalPermit with sensible defaults for testing.
    Override individual fields as needed.
    """
    return CanonicalPermit(
        permit_id=permit_id,
        city=city,
        state=state,
        jurisdiction=jurisdiction,
        permit_type=permit_type,
        permit_status=permit_status,
        occupancy_type=occupancy_type,
        valuation=valuation,
        address=address,
        project_description=project_description,
        data_source=data_source,
        fetched_at=datetime(2026, 4, 12, 12, 0, 0),
        raw_data=raw_data or {},
        filing_date=filing_date or date(2026, 1, 15),
        owner_name=owner_name,
        applicant_name=applicant_name,
    )


@pytest.fixture
def commercial_new_construction():
    """High-relevance permit: commercial new construction, $10M, under review."""
    return make_permit(
        permit_type=PermitType.NEW_CONSTRUCTION,
        permit_status=PermitStatus.UNDER_REVIEW,
        occupancy_type=OccupancyType.COMMERCIAL,
        valuation=10_000_000.0,
    )


@pytest.fixture
def commercial_below_threshold():
    """Below the $500K PADFP threshold — ordinance won't trigger."""
    return make_permit(
        permit_type=PermitType.NEW_CONSTRUCTION,
        permit_status=PermitStatus.UNDER_REVIEW,
        occupancy_type=OccupancyType.COMMERCIAL,
        valuation=300_000.0,
    )


@pytest.fixture
def single_family_large():
    """Single-family residential — irrelevant regardless of valuation."""
    return make_permit(
        permit_type=PermitType.NEW_CONSTRUCTION,
        permit_status=PermitStatus.UNDER_REVIEW,
        occupancy_type=OccupancyType.RESIDENTIAL_SINGLE,
        valuation=50_000_000.0,
    )


@pytest.fixture
def null_valuation_commercial():
    """Commercial permit with no valuation — engine should not crash."""
    return make_permit(
        permit_type=PermitType.NEW_CONSTRUCTION,
        permit_status=PermitStatus.UNDER_REVIEW,
        occupancy_type=OccupancyType.COMMERCIAL,
        valuation=None,
    )


@pytest.fixture
def la_ordinances():
    """Load the actual percent_for_art.json from disk."""
    from permits.engine import load_ordinances
    return load_ordinances()
