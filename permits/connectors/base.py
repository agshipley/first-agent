"""
Abstract connector interface.

Every connector — whether Socrata, a commercial API, or a CSV import —
must implement BaseConnector. The intelligence engine and routes work
against this interface only.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from permits.schema import CanonicalPermit


@dataclass
class ConnectorFilters:
    """Filters that any connector must understand and apply."""
    min_valuation: float = 5_000_000
    # "all" | "new" | "alteration" | "addition"
    permit_type: str = "all"
    # "all" | "commercial" | "apartment"
    occupancy_type: str = "all"
    # "pipeline" → UNDER_REVIEW + APPROVED
    # "issued"   → ISSUED + FINAL
    # "all"      → no status filter
    status_category: str = "pipeline"
    date_from: str = ""          # YYYY-MM-DD applied to the primary date field
    limit: int = 50
    # "submitted" | "issued" | "both"  (connector-specific — not all connectors
    # have multiple datasets, but the LA connector does)
    source: str = "submitted"


@dataclass
class ConnectorMetadata:
    """Describes what a connector covers and how fresh its data is."""
    city: str
    state: str
    datasets: list[dict]         # [{id, name, role, primary_sort_field}, ...]
    data_freshness: str          # human-readable, e.g. "~weekly"
    available_filter_fields: list[str] = field(default_factory=list)
    known_limitations: list[str] = field(default_factory=list)


class BaseConnector(ABC):
    """
    All connectors implement this interface.
    The engine calls fetch(); the routes call get_metadata() for health checks.
    """

    @abstractmethod
    def fetch(self, filters: ConnectorFilters) -> list[CanonicalPermit]:
        """
        Fetch permits matching filters and return them as CanonicalPermit records.
        Must raise RuntimeError on unrecoverable data source errors.
        """
        ...

    @abstractmethod
    def get_metadata(self) -> ConnectorMetadata:
        """Return static metadata about this connector."""
        ...
