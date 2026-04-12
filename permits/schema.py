"""
Canonical permit data model.

Every connector normalizes its source data into CanonicalPermit.
The intelligence engine reads only this schema — it never touches raw source data.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class PermitType(str, Enum):
    NEW_CONSTRUCTION = "NEW_CONSTRUCTION"
    MAJOR_RENOVATION = "MAJOR_RENOVATION"
    ADDITION = "ADDITION"
    DEMOLITION = "DEMOLITION"
    OTHER = "OTHER"


class PermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    FINAL = "FINAL"
    EXPIRED = "EXPIRED"


class OccupancyType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    RESIDENTIAL_MULTI = "RESIDENTIAL_MULTI"
    RESIDENTIAL_SINGLE = "RESIDENTIAL_SINGLE"
    MIXED_USE = "MIXED_USE"
    CIVIC = "CIVIC"
    EDUCATIONAL = "EDUCATIONAL"
    INDUSTRIAL = "INDUSTRIAL"
    OTHER = "OTHER"


# Statuses that indicate a permit is still in the pipeline (not yet issued)
PIPELINE_STATUSES = {PermitStatus.UNDER_REVIEW, PermitStatus.APPROVED}

# Statuses that indicate the permit has been issued or finalized
ISSUED_STATUSES = {PermitStatus.ISSUED, PermitStatus.FINAL}


@dataclass
class CanonicalPermit:
    # ── Required ──────────────────────────────────────────────────────────────
    permit_id: str
    city: str
    state: str
    jurisdiction: str
    permit_type: PermitType
    permit_status: PermitStatus
    project_description: str
    address: str
    data_source: str
    fetched_at: datetime

    # ── Optional ──────────────────────────────────────────────────────────────
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    valuation: Optional[float] = None
    occupancy_type: OccupancyType = OccupancyType.OTHER
    applicant_name: Optional[str] = None
    owner_name: Optional[str] = None
    filing_date: Optional[date] = None
    approval_date: Optional[date] = None
    raw_data: dict = field(default_factory=dict)

    def to_dict(self, include_raw: bool = False) -> dict:
        """Return a JSON-serializable dict suitable for API responses."""
        d: dict = {
            "permit_id": self.permit_id,
            "city": self.city,
            "state": self.state,
            "jurisdiction": self.jurisdiction,
            "permit_type": self.permit_type.value,
            "permit_status": self.permit_status.value,
            "project_description": self.project_description,
            "address": self.address,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "valuation": self.valuation,
            "valuation_display": (
                f"${int(self.valuation):,}" if self.valuation is not None else ""
            ),
            "occupancy_type": self.occupancy_type.value,
            "applicant_name": self.applicant_name,
            "owner_name": self.owner_name,
            "filing_date": self.filing_date.isoformat() if self.filing_date else None,
            "approval_date": (
                self.approval_date.isoformat() if self.approval_date else None
            ),
            "data_source": self.data_source,
            "fetched_at": self.fetched_at.isoformat(),
            # UI conveniences derived from raw_data (set by connector, not schema)
            "neighborhood": self.raw_data.get("cpa") or self.raw_data.get("apc") or "",
            "council_district": self.raw_data.get("cd", ""),
        }
        if include_raw:
            d["raw_data"] = self.raw_data
        return d
