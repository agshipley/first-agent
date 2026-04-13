"""
Permits Intelligence Engine — art commissioning relevance scoring.

Entry point:
  score_permit(permit, ordinances) → ScoredPermit

The engine reads only the CanonicalPermit schema and the ordinance JSON structure.
It has no knowledge of Socrata, LADBS field names, or any city connector internals.

Current capabilities (Phase 1):
  - Percent-for-art ordinance matching (does this permit trigger an ordinance?)
  - Estimated art budget (ordinance % × project valuation, expressed as a range)
  - Art commissioning relevance score: High / Medium / Low / None

Scoring logic is programmatic. No LLM calls. Each decision is traceable to a
specific rule and can be verified or overridden by updating ordinance data or
the scoring constants below.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from permits.schema import CanonicalPermit, OccupancyType, PermitStatus, PermitType


# ── Scoring constants ─────────────────────────────────────────────────────────
# These drive the relevance score. Change them here, not scattered through logic.

# Occupancy types ordered by art commissioning relevance.
# Commercial and civic spaces are the core market; residential multi-family
# qualifies under PADFP but is lower priority for Tre Borden /Co specifically.
_OCCUPANCY_WEIGHT: dict[OccupancyType, int] = {
    OccupancyType.COMMERCIAL:         3,
    OccupancyType.CIVIC:              3,
    OccupancyType.MIXED_USE:          3,
    OccupancyType.EDUCATIONAL:        2,
    OccupancyType.RESIDENTIAL_MULTI:  1,
    OccupancyType.INDUSTRIAL:         0,
    OccupancyType.RESIDENTIAL_SINGLE: 0,
    OccupancyType.OTHER:              1,
}

# Permit types carry timing signal: new construction is highest value because
# art decisions happen earliest; demolition is irrelevant.
_TYPE_WEIGHT: dict[PermitType, int] = {
    PermitType.NEW_CONSTRUCTION: 3,
    PermitType.ADDITION:         2,
    PermitType.MAJOR_RENOVATION: 2,
    PermitType.OTHER:            1,
    PermitType.DEMOLITION:       0,
}

# Permit statuses: earlier pipeline = higher value for outreach timing.
_STATUS_WEIGHT: dict[PermitStatus, int] = {
    PermitStatus.UNDER_REVIEW: 3,   # earliest signal
    PermitStatus.APPROVED:     3,   # about to start
    PermitStatus.ISSUED:       2,   # construction beginning
    PermitStatus.FINAL:        1,   # late stage, still possible
    PermitStatus.SUBMITTED:    3,
    PermitStatus.EXPIRED:      0,
}

# Valuation bands: raw threshold → weight
_VALUATION_BANDS = [
    (50_000_000, 4),   # $50M+
    (20_000_000, 3),   # $20M–$50M
    (10_000_000, 2),   # $10M–$20M
    (5_000_000,  1),   # $5M–$10M
    (0,          0),   # below $5M
]

# Score thresholds → RelevanceLevel
_HIGH_THRESHOLD   = 9   # ordinance triggered + strong occupancy + high valuation
_MEDIUM_THRESHOLD = 5   # ordinance triggered or strong occupancy with decent valuation

# Minimum valuation required for HIGH relevance when no ordinance triggered.
# Without a formal percent-for-art requirement, voluntary art commissioning is
# only plausible at a meaningful project scale.
_HIGH_NO_ORDINANCE_MIN_VALUATION = 5_000_000


# ── Ordinance matching ────────────────────────────────────────────────────────

# Maps occupancy_type enum values to the project_types strings used in the
# ordinance JSON. This is the only coupling between engine and ordinance data format.
_OCCUPANCY_TO_ORDINANCE_TYPES: dict[OccupancyType, list[str]] = {
    OccupancyType.COMMERCIAL:         ["Commercial", "Office", "Hotel"],
    OccupancyType.RESIDENTIAL_MULTI:  ["Apartment", "Mixed-Use"],
    OccupancyType.MIXED_USE:          ["Mixed-Use", "Commercial"],
    OccupancyType.CIVIC:              ["Public Capital Projects"],
    OccupancyType.EDUCATIONAL:        ["Commercial"],  # schools rarely private dev
    OccupancyType.INDUSTRIAL:         ["Industrial"],
    OccupancyType.RESIDENTIAL_SINGLE: [],
    OccupancyType.OTHER:              ["Commercial"],
}


# ── Output types ──────────────────────────────────────────────────────────────

class RelevanceLevel(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"
    NONE   = "None"    # permit is irrelevant (demolition, expired, single-family, etc.)


@dataclass
class OrdMatchResult:
    """Result of checking one ordinance against one permit."""
    triggered: bool
    ordinance_name: str
    ordinance_percentage: float
    art_budget_low: Optional[float]   # ordinance % × valuation × 0.8 (conservative)
    art_budget_high: Optional[float]  # ordinance % × valuation × 1.2 (optimistic)
    reason: str                       # human-readable explanation


@dataclass
class ScoredPermit:
    """
    A CanonicalPermit enriched with art commissioning intelligence.
    The original permit is preserved unchanged; scoring fields are additive.
    """
    permit: CanonicalPermit

    # Ordinance match
    ordinance_triggered: bool
    ordinance_name: Optional[str]            # name of the triggered ordinance, if any
    ordinance_match_reason: str              # why it does/doesn't trigger

    # Art budget estimate
    art_budget_low: Optional[float]          # lower bound in USD
    art_budget_high: Optional[float]         # upper bound in USD
    art_budget_display: str                  # formatted range, e.g. "$80K–$120K"
    budget_basis: str                        # one-sentence derivation

    # Relevance
    relevance: RelevanceLevel
    relevance_reasons: list[str]             # bullet points explaining the score

    def to_dict(self) -> dict:
        d = self.permit.to_dict()
        d.update({
            "ordinance_triggered": self.ordinance_triggered,
            "ordinance_name":      self.ordinance_name,
            "art_budget_display":  self.art_budget_display,
            "budget_basis":        self.budget_basis,
            "relevance":           self.relevance.value,
            "relevance_reasons":   self.relevance_reasons,
        })
        return d


# ── Ordinance loader ──────────────────────────────────────────────────────────

def load_ordinances(path: Optional[str] = None) -> list[dict]:
    """
    Load percent-for-art ordinance data from the JSON file.
    Returns the raw list of ordinance dicts — the engine consumes this directly.
    """
    if path is None:
        path = os.path.join(
            os.path.dirname(__file__),
            "ordinances", "data", "percent_for_art.json"
        )
    with open(path, "r") as f:
        return json.load(f)


# ── Core scoring function ─────────────────────────────────────────────────────

def score_permit(
    permit: CanonicalPermit,
    ordinances: list[dict],
) -> ScoredPermit:
    """
    Score a single CanonicalPermit for art commissioning relevance.

    Steps:
      1. Check all ordinances for city/state match and project eligibility.
      2. If an ordinance triggers, compute the art budget estimate.
      3. Compute a composite relevance score from ordinance match, occupancy
         type, permit type, status, and valuation.
      4. Return a ScoredPermit with all scoring fields populated.
    """
    # ── Step 1: ordinance matching ────────────────────────────────────────────
    ord_result = _match_ordinances(permit, ordinances)

    # ── Step 2: compute relevance score ──────────────────────────────────────
    score, reasons = _compute_score(permit, ord_result)

    # ── Step 3: map score to RelevanceLevel ───────────────────────────────────
    # Immediately disqualify cases where art commissioning is implausible.
    if _is_irrelevant(permit):
        relevance = RelevanceLevel.NONE
        reasons = ["Project type or status does not support art commissioning."]
    elif score >= _HIGH_THRESHOLD:
        # Valuation floor: without an ordinance trigger, require $5M+ for HIGH.
        # Category weights alone (occupancy + type + status) can sum to 9 on a
        # $300K tenant improvement — that's not a project Tre would pursue.
        # A $5M+ project without a formal ordinance can still warrant outreach
        # because voluntary art commissioning is plausible at that scale.
        if not ord_result.triggered and (permit.valuation or 0) < _HIGH_NO_ORDINANCE_MIN_VALUATION:
            relevance = RelevanceLevel.MEDIUM
            val_str = f"${permit.valuation:,.0f}" if permit.valuation is not None else "unknown"
            reasons.append(
                f"Capped at Medium: no ordinance triggered and valuation "
                f"{val_str} is below the "
                f"${_HIGH_NO_ORDINANCE_MIN_VALUATION:,.0f} floor for High relevance "
                f"without an ordinance requirement."
            )
        else:
            relevance = RelevanceLevel.HIGH
    elif score >= _MEDIUM_THRESHOLD:
        relevance = RelevanceLevel.MEDIUM
    else:
        relevance = RelevanceLevel.LOW

    # ── Step 4: budget display ────────────────────────────────────────────────
    budget_display, budget_basis = _format_budget(permit, ord_result)

    return ScoredPermit(
        permit=permit,
        ordinance_triggered=ord_result.triggered,
        ordinance_name=ord_result.ordinance_name if ord_result.triggered else None,
        ordinance_match_reason=ord_result.reason,
        art_budget_low=ord_result.art_budget_low,
        art_budget_high=ord_result.art_budget_high,
        art_budget_display=budget_display,
        budget_basis=budget_basis,
        relevance=relevance,
        relevance_reasons=reasons,
    )


def score_permits(
    permits: list[CanonicalPermit],
    ordinances: Optional[list[dict]] = None,
) -> list[ScoredPermit]:
    """Score a list of permits. Loads ordinances from disk if not provided."""
    if ordinances is None:
        ordinances = load_ordinances()
    return [score_permit(p, ordinances) for p in permits]


# ── Ordinance matching logic ──────────────────────────────────────────────────

def _match_ordinances(permit: CanonicalPermit, ordinances: list[dict]) -> OrdMatchResult:
    """
    Find the best-matching triggered ordinance for this permit.
    Returns the first ordinance that triggers, or a non-triggered result.
    """
    city_ordinances = [
        o for o in ordinances
        if o.get("city") == permit.city and o.get("state") == permit.state
    ]

    if not city_ordinances:
        return OrdMatchResult(
            triggered=False,
            ordinance_name="",
            ordinance_percentage=0.0,
            art_budget_low=None,
            art_budget_high=None,
            reason=f"No percent-for-art ordinance data for {permit.city}, {permit.state}.",
        )

    for ord_data in city_ordinances:
        result = _check_ordinance(permit, ord_data)
        if result.triggered:
            return result

    # No ordinance triggered — return the last check's reason
    return _check_ordinance(permit, city_ordinances[0])


def _check_ordinance(permit: CanonicalPermit, ord_data: dict) -> OrdMatchResult:
    """Check whether a single ordinance applies to this permit."""
    name = ord_data.get("ordinance_name", "Unknown Ordinance")
    pct  = ord_data.get("percentage", 0.0)

    # Valuation check
    threshold = ord_data.get("valuation_threshold")
    if threshold is not None:
        if permit.valuation is None:
            return OrdMatchResult(
                triggered=False,
                ordinance_name=name,
                ordinance_percentage=pct,
                art_budget_low=None,
                art_budget_high=None,
                reason="Permit valuation unknown — cannot determine ordinance threshold.",
            )
        if permit.valuation < threshold:
            return OrdMatchResult(
                triggered=False,
                ordinance_name=name,
                ordinance_percentage=pct,
                art_budget_low=None,
                art_budget_high=None,
                reason=(
                    f"Valuation ${permit.valuation:,.0f} is below "
                    f"the ${threshold:,.0f} threshold for {name}."
                ),
            )

    # Project type check: does this permit's occupancy type match what the ordinance covers?
    applicable_types: list[str] = ord_data.get("project_types", [])
    occupancy_types_for_permit = _OCCUPANCY_TO_ORDINANCE_TYPES.get(
        permit.occupancy_type, []
    )
    type_match = any(t in applicable_types for t in occupancy_types_for_permit)

    if not type_match:
        return OrdMatchResult(
            triggered=False,
            ordinance_name=name,
            ordinance_percentage=pct,
            art_budget_low=None,
            art_budget_high=None,
            reason=(
                f"{permit.occupancy_type.value} projects do not trigger {name}."
            ),
        )

    # Ordinance triggered — compute budget estimate
    budget_low  = permit.valuation * pct * 0.8 if permit.valuation else None
    budget_high = permit.valuation * pct * 1.2 if permit.valuation else None

    return OrdMatchResult(
        triggered=True,
        ordinance_name=name,
        ordinance_percentage=pct,
        art_budget_low=budget_low,
        art_budget_high=budget_high,
        reason=(
            f"Triggers {name}: valuation ${permit.valuation:,.0f} "
            f"exceeds ${threshold:,.0f} threshold. "
            f"Estimated {pct*100:.0f}% art budget."
        ) if threshold else (
            f"Triggers {name}: {pct*100:.0f}% applies to this project type."
        ),
    )


# ── Relevance scoring ─────────────────────────────────────────────────────────

def _is_irrelevant(permit: CanonicalPermit) -> bool:
    """True for permits where art commissioning is implausible."""
    if permit.permit_type == PermitType.DEMOLITION:
        return True
    if permit.permit_status == PermitStatus.EXPIRED:
        return True
    if permit.occupancy_type == OccupancyType.RESIDENTIAL_SINGLE:
        return True
    if permit.occupancy_type == OccupancyType.INDUSTRIAL:
        return True
    return False


def _compute_score(
    permit: CanonicalPermit,
    ord_result: OrdMatchResult,
) -> tuple[int, list[str]]:
    """
    Compute a composite integer score and a list of plain-English reasons.
    Higher is more relevant.
    """
    score = 0
    reasons: list[str] = []

    # Ordinance match is the primary signal — it doubles the base score
    if ord_result.triggered:
        score += 6
        reasons.append(
            f"Triggers {ord_result.ordinance_name} "
            f"({ord_result.ordinance_percentage * 100:.0f}% of construction cost)."
        )
    else:
        reasons.append(ord_result.reason)

    # Occupancy type
    occ_w = _OCCUPANCY_WEIGHT.get(permit.occupancy_type, 1)
    score += occ_w
    if occ_w >= 3:
        reasons.append(
            f"{permit.occupancy_type.value.replace('_', ' ').title()} — "
            "high-priority project type for art commissioning."
        )
    elif occ_w == 0:
        reasons.append(
            f"{permit.occupancy_type.value.replace('_', ' ').title()} — "
            "low priority for art commissioning."
        )

    # Permit type
    type_w = _TYPE_WEIGHT.get(permit.permit_type, 1)
    score += type_w
    if permit.permit_type == PermitType.NEW_CONSTRUCTION:
        reasons.append("New construction — art decisions happen earliest in this phase.")
    elif permit.permit_type in (PermitType.MAJOR_RENOVATION, PermitType.ADDITION):
        reasons.append("Renovation or addition — art commissioning still possible.")

    # Status timing
    status_w = _STATUS_WEIGHT.get(permit.permit_status, 1)
    score += status_w
    if permit.permit_status in (PermitStatus.UNDER_REVIEW, PermitStatus.APPROVED, PermitStatus.SUBMITTED):
        reasons.append("Pre-issuance — early enough to influence art decisions.")
    elif permit.permit_status == PermitStatus.FINAL:
        reasons.append("Near completion — late stage, window may be closing.")

    # Valuation
    val_w = 0
    for threshold, weight in _VALUATION_BANDS:
        if permit.valuation and permit.valuation >= threshold:
            val_w = weight
            break
    score += val_w
    if permit.valuation and permit.valuation >= 20_000_000:
        reasons.append(
            f"${permit.valuation/1_000_000:.0f}M valuation — "
            "large project, significant art budget likely."
        )
    elif permit.valuation and permit.valuation >= 5_000_000:
        reasons.append(
            f"${permit.valuation/1_000_000:.1f}M valuation — "
            "mid-scale project, meaningful art budget possible."
        )

    return score, reasons


# ── Budget formatting ─────────────────────────────────────────────────────────

def _format_budget(
    permit: CanonicalPermit,
    ord_result: OrdMatchResult,
) -> tuple[str, str]:
    """Return (display_string, basis_sentence) for the art budget estimate."""
    if ord_result.triggered and ord_result.art_budget_low is not None:
        low  = ord_result.art_budget_low
        high = ord_result.art_budget_high or low
        display = f"${_fmt_k(low)}–${_fmt_k(high)}"
        basis = (
            f"{ord_result.ordinance_percentage * 100:.0f}% of "
            f"${permit.valuation:,.0f} construction cost per "
            f"{ord_result.ordinance_name}."
        )
        return display, basis

    # No ordinance — use a market-heuristic range (0.5%–1.5% of valuation)
    if permit.valuation and permit.valuation >= 5_000_000:
        low  = permit.valuation * 0.005
        high = permit.valuation * 0.015
        display = f"${_fmt_k(low)}–${_fmt_k(high)}"
        basis = (
            "Estimated 0.5%–1.5% of construction cost; "
            "no applicable ordinance confirmed."
        )
        return display, basis

    return "", "Valuation below threshold or unknown."


def _fmt_k(value: float) -> str:
    """Format a dollar value as a compact string: $1,250,000 → '1.25M', $75,000 → '75K'."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2g}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"
