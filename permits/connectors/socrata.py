"""
Generic Socrata SODA API connector.

SocrataConnector implements BaseConnector for any Socrata-powered open data
portal. City-specific behavior (dataset IDs, field names, enum mappings) is
supplied via SocrataConfig — see connectors/cities/ for examples.

Valuation note: LADBS datasets store valuation as text. Numeric $where
comparisons fail. We use `length(valuation) >= N` as a server-side pre-filter
and apply the exact numeric threshold in Python post-fetch. This is a known
quirk of the LADBS dataset format — other cities may not need this workaround.
"""

import time
import httpx
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

from permits.schema import (
    CanonicalPermit,
    PermitType,
    PermitStatus,
    OccupancyType,
    PIPELINE_STATUSES,
    ISSUED_STATUSES,
)
from permits.connectors.base import BaseConnector, ConnectorFilters, ConnectorMetadata

CACHE_TTL_SECONDS = 3600

# Module-level cache shared across all SocrataConnector instances.
# Key: (dataset_url, where_clause, order, limit_str)
_cache: dict[tuple, tuple[float, list[dict]]] = {}


@dataclass
class SocrataDataset:
    """Configuration for a single Socrata dataset."""
    id: str                          # Socrata 4x4 dataset ID
    name: str                        # Human-readable name
    role: str                        # "submitted" | "issued"
    primary_sort_field: str          # Field to ORDER BY and apply date_from to
    has_coordinates: bool = False    # Whether lat/lon are present in this dataset


@dataclass
class SocrataConfig:
    """
    Everything a SocrataConnector needs to connect to a city's permit data
    and normalize it into CanonicalPermit records.

    The field_map maps canonical field names to the source field names
    used in the Socrata dataset. The *_map dicts map source values to
    canonical enum names (as strings matching the enum member names).
    """
    city: str
    state: str
    jurisdiction: str
    socrata_domain: str              # e.g., "data.lacity.org"
    datasets: dict[str, SocrataDataset]  # keyed by role: "submitted", "issued"

    # Source field names used in $where clauses
    permit_type_field: str
    status_field: str
    occupancy_type_field: str
    valuation_field: str

    # Normalization: canonical_key → source_field_name
    field_map: dict[str, str]

    # Enum mappings: source_value → canonical enum member name (string)
    permit_type_map: dict[str, str]
    permit_status_map: dict[str, str]
    occupancy_type_map: dict[str, str]

    # Optional: which permit_type and occupancy_type source values to include
    # by default when "all" is selected. If empty, no filter is applied.
    default_permit_types: list[str] = field(default_factory=list)
    default_occupancy_types: list[str] = field(default_factory=list)

    data_freshness: str = "unknown"
    known_limitations: list[str] = field(default_factory=list)


class SocrataConnector(BaseConnector):
    """
    Generic Socrata connector. Parameterized by SocrataConfig.
    """

    def __init__(self, config: SocrataConfig):
        self._cfg = config
        # Pre-compute pipeline and issued status sets from the config mapping
        self._pipeline_statuses = {
            raw for raw, canonical in config.permit_status_map.items()
            if canonical in ("UNDER_REVIEW", "APPROVED")
        }
        self._issued_statuses = {
            raw for raw, canonical in config.permit_status_map.items()
            if canonical in ("ISSUED", "FINAL")
        }

    # ── Public interface ───────────────────────────────────────────────────────

    def fetch(self, filters: ConnectorFilters) -> list[CanonicalPermit]:
        """
        Fetch and normalize permits. Queries one or both Socrata datasets
        depending on filters.source. Results are merged and deduplicated on
        permit_id when source="both".
        """
        datasets_to_query: list[SocrataDataset] = []
        if filters.source == "both":
            datasets_to_query = list(self._cfg.datasets.values())
        elif filters.source in self._cfg.datasets:
            datasets_to_query = [self._cfg.datasets[filters.source]]
        else:
            # Fallback: use the first available dataset
            datasets_to_query = [next(iter(self._cfg.datasets.values()))]

        all_permits: list[CanonicalPermit] = []
        seen_ids: set[str] = set()

        for dataset in datasets_to_query:
            rows = self._fetch_raw(dataset, filters)
            fetched_at = datetime.utcnow()
            for row in rows:
                permit = self._normalize(row, dataset, fetched_at)
                if permit and permit.permit_id not in seen_ids:
                    all_permits.append(permit)
                    seen_ids.add(permit.permit_id)

        # Sort: most recent first (filing_date for submitted, approval_date for issued)
        all_permits.sort(
            key=lambda p: (p.filing_date or p.approval_date or date.min),
            reverse=True,
        )

        return all_permits[:filters.limit]

    def get_metadata(self) -> ConnectorMetadata:
        return ConnectorMetadata(
            city=self._cfg.city,
            state=self._cfg.state,
            datasets=[
                {
                    "id": ds.id,
                    "name": ds.name,
                    "role": ds.role,
                    "primary_sort_field": ds.primary_sort_field,
                    "has_coordinates": ds.has_coordinates,
                }
                for ds in self._cfg.datasets.values()
            ],
            data_freshness=self._cfg.data_freshness,
            available_filter_fields=[
                self._cfg.permit_type_field,
                self._cfg.status_field,
                self._cfg.occupancy_type_field,
                self._cfg.valuation_field,
            ],
            known_limitations=self._cfg.known_limitations,
        )

    # ── Internal: fetching ─────────────────────────────────────────────────────

    def _dataset_url(self, dataset: SocrataDataset) -> str:
        return f"https://{self._cfg.socrata_domain}/resource/{dataset.id}.json"

    def _fetch_raw(
        self, dataset: SocrataDataset, filters: ConnectorFilters
    ) -> list[dict]:
        """
        Fetch raw rows from Socrata for the given dataset and filters.
        Uses in-memory caching with CACHE_TTL_SECONDS TTL.
        """
        where = self._build_where(dataset, filters)
        order = f"{dataset.primary_sort_field} DESC"
        # Fetch extra rows to compensate for the post-filter valuation drop-off
        fetch_limit = min(filters.limit * 10, 2000)

        cache_key = (self._dataset_url(dataset), where, order, str(fetch_limit))
        cached = _cache.get(cache_key)
        if cached:
            ts, rows = cached
            if time.time() - ts < CACHE_TTL_SECONDS:
                return rows

        query = {"$where": where, "$order": order, "$limit": fetch_limit}
        url = self._dataset_url(dataset)

        # 10 s connect, 45 s read — issued dataset is slower than submitted.
        timeout = httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=10.0)
        last_exc: Exception | None = None
        for attempt in range(2):  # one retry on timeout
            try:
                with httpx.Client(timeout=timeout) as client:
                    resp = client.get(url, params=query)
                    resp.raise_for_status()
                    rows = resp.json()
                    break
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(2)
                    continue
                raise RuntimeError(
                    f"Socrata fetch timed out after 2 attempts ({url}). "
                    f"The LA open data portal may be slow — try again in a moment."
                ) from exc
            except Exception as exc:
                raise RuntimeError(f"Socrata fetch error ({url}): {exc}") from exc
        else:
            raise RuntimeError(f"Socrata fetch error ({url}): {last_exc}") from last_exc

        if not isinstance(rows, list):
            raise RuntimeError(f"Unexpected Socrata response from {url}: {rows}")

        _cache[cache_key] = (time.time(), rows)
        return rows

    def _build_where(self, dataset: SocrataDataset, filters: ConnectorFilters) -> str:
        """Build the Socrata $where clause for the given dataset and filters."""
        cfg = self._cfg
        clauses: list[str] = []

        # Valuation pre-filter (text field — exact threshold applied post-fetch)
        if filters.min_valuation > 0:
            prefilter_len = len(str(int(filters.min_valuation)))
            clauses.append(
                f"length({cfg.valuation_field}) >= {prefilter_len}"
            )

        # Permit type filter
        if filters.permit_type != "all":
            type_ui_map = {
                "new": "Bldg-New",
                "alteration": "Bldg-Alter/Repair",
                "addition": "Bldg-Addition",
            }
            raw_type = type_ui_map.get(filters.permit_type)
            if raw_type:
                clauses.append(f"{cfg.permit_type_field}='{raw_type}'")
        elif cfg.default_permit_types:
            vals = ", ".join(f"'{v}'" for v in cfg.default_permit_types)
            clauses.append(f"{cfg.permit_type_field} in({vals})")

        # Occupancy type filter
        if filters.occupancy_type != "all":
            occ_ui_map = {"commercial": "Commercial", "apartment": "Apartment"}
            raw_occ = occ_ui_map.get(filters.occupancy_type)
            if raw_occ:
                clauses.append(f"{cfg.occupancy_type_field}='{raw_occ}'")
        elif cfg.default_occupancy_types:
            vals = ", ".join(f"'{v}'" for v in cfg.default_occupancy_types)
            clauses.append(f"{cfg.occupancy_type_field} in({vals})")

        # Status filter
        if filters.status_category == "pipeline":
            statuses = self._pipeline_statuses
        elif filters.status_category == "issued":
            statuses = self._issued_statuses
        else:
            statuses = set()

        if statuses:
            vals = ", ".join(f"'{s}'" for s in sorted(statuses))
            clauses.append(f"{cfg.status_field} in({vals})")

        # Date filter — applied to the dataset's primary sort field
        if filters.date_from:
            clauses.append(
                f"{dataset.primary_sort_field}>='{filters.date_from}T00:00:00.000'"
            )

        return " AND ".join(clauses) if clauses else "permit_group='Building'"

    # ── Internal: normalization ────────────────────────────────────────────────

    def _normalize(
        self,
        row: dict,
        dataset: SocrataDataset,
        fetched_at: datetime,
    ) -> Optional[CanonicalPermit]:
        """Normalize a raw Socrata row into a CanonicalPermit. Returns None to skip."""
        cfg = self._cfg
        fm = cfg.field_map

        # Valuation — parse text to float, post-filter handled by caller
        valuation = self._parse_valuation(row.get(cfg.valuation_field))

        # CanonicalPermit requires a permit_id
        permit_id = row.get(fm.get("permit_id", "permit_nbr"), "").strip()
        if not permit_id:
            return None

        # Enum mappings with defaults
        raw_type = row.get(fm.get("permit_type_raw", cfg.permit_type_field), "")
        permit_type = PermitType(
            cfg.permit_type_map.get(raw_type, "OTHER")
        )

        raw_status = row.get(fm.get("permit_status_raw", cfg.status_field), "")
        permit_status = PermitStatus(
            cfg.permit_status_map.get(raw_status, "UNDER_REVIEW")
        )

        raw_occ = row.get(fm.get("occupancy_type_raw", cfg.occupancy_type_field), "")
        # Fall back to use_desc if sub_type doesn't map cleanly
        if not raw_occ or raw_occ not in cfg.occupancy_type_map:
            raw_occ = row.get("use_desc", "")
        occupancy_type = OccupancyType(
            cfg.occupancy_type_map.get(raw_occ, "OTHER")
        )

        # Coordinates — only in issued dataset for LA
        latitude: Optional[float] = None
        longitude: Optional[float] = None
        if dataset.has_coordinates:
            latitude = self._parse_float(row.get(fm.get("latitude", "lat")))
            longitude = self._parse_float(row.get(fm.get("longitude", "lon")))

        return CanonicalPermit(
            permit_id=permit_id,
            city=cfg.city,
            state=cfg.state,
            jurisdiction=cfg.jurisdiction,
            permit_type=permit_type,
            permit_status=permit_status,
            project_description=row.get(fm.get("project_description", "work_desc"), ""),
            address=row.get(fm.get("address", "primary_address"), ""),
            latitude=latitude,
            longitude=longitude,
            valuation=valuation,
            occupancy_type=occupancy_type,
            applicant_name=row.get(fm.get("applicant_name", ""), None) or None,
            owner_name=row.get(fm.get("owner_name", ""), None) or None,
            filing_date=self._parse_date(
                row.get(fm.get("filing_date", "submitted_date"))
            ),
            approval_date=self._parse_date(
                row.get(fm.get("approval_date", "issue_date"))
            ),
            data_source=f"{cfg.socrata_domain}/{dataset.id}",
            raw_data=row,
            fetched_at=fetched_at,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_valuation(raw: object) -> Optional[float]:
        """Parse a text valuation field to float. Returns None if empty or malformed."""
        if not raw:
            return None
        try:
            return float(str(raw).strip())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_float(raw: object) -> Optional[float]:
        if not raw:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_date(raw: object) -> Optional[date]:
        """Parse an ISO date string (YYYY-MM-DDTHH:MM:SS.sss) to a date object."""
        if not raw:
            return None
        try:
            return date.fromisoformat(str(raw)[:10])
        except (ValueError, TypeError):
            return None
