"""
Permits Intelligence Engine.

Public surface:
  CanonicalPermit, PermitType, PermitStatus, OccupancyType  — data model
  la_connector                                               — LA Socrata connector
  permits_bp                                                 — Flask blueprint
"""

from permits.schema import CanonicalPermit, PermitType, PermitStatus, OccupancyType
from permits.connectors.cities.los_angeles import la_connector
from permits.connectors.cities.new_york import nyc_connector
from permits.routes import permits_bp
from permits.engine import ScoredPermit, RelevanceLevel, score_permit, score_permits, load_ordinances

__all__ = [
    "CanonicalPermit",
    "PermitType",
    "PermitStatus",
    "OccupancyType",
    "la_connector",
    "nyc_connector",
    "permits_bp",
    "ScoredPermit",
    "RelevanceLevel",
    "score_permit",
    "score_permits",
    "load_ordinances",
]
