"""
Permits Intelligence Engine — art commissioning relevance scoring.

Entry point:
  score_permit(permit, ordinances) -> ScoredPermit

The engine reads only the CanonicalPermit schema, the ordinance JSON, and
the owner_patterns.json configuration. It has no knowledge of Socrata,
LADBS field names, or any city connector internals.

Scoring philosophy (v2):
  Typology and owner signals are the strongest predictors of actual art
  commissioning. Hotels, cultural institutions, and landmark towers almost
  always include art programs regardless of ordinance status. Public-sector
  projects with strong percent-for-art ordinances are high certainty.

  Weak ordinances (LA PADFP, SF Section 429) have historically generated
  few commissions and are treated as soft contextual signals, not primary
  scoring factors.

  Scoring is programmatic. No LLM calls. Each decision is traceable to a
  specific rule and can be verified by updating ordinance data, owner
  patterns, or the scoring constants below.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from permits.schema import CanonicalPermit, OccupancyType, PermitStatus, PermitType


# ── Owner pattern loader ─────────────────────────────────────────────────────

def _load_owner_patterns() -> dict:
    path = os.path.join(os.path.dirname(__file__), "scoring", "owner_patterns.json")
    try:
        with open(path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

_OWNER_PATTERNS = _load_owner_patterns()


# ── Scoring constants ────────────────────────────────────────────────────────

# A. TYPOLOGY — strongest scoring factor
# Maps occupancy type -> score bump. Hotels and cultural get the biggest boost.
_TYPOLOGY_BUMP: dict[OccupancyType, int] = {
    OccupancyType.COMMERCIAL:         1,   # base; hotels get extra via keywords
    OccupancyType.CIVIC:              2,
    OccupancyType.EDUCATIONAL:        2,
    OccupancyType.MIXED_USE:          1,
    OccupancyType.RESIDENTIAL_MULTI:  0,
    OccupancyType.INDUSTRIAL:         0,
    OccupancyType.RESIDENTIAL_SINGLE: 0,
    OccupancyType.OTHER:              0,
}

# Hard-cap occupancy types: these NEVER score above None
_IRRELEVANT_OCCUPANCY = {
    OccupancyType.RESIDENTIAL_SINGLE,
    OccupancyType.INDUSTRIAL,
}

# B. KEYWORD SIGNALS — expanded lists
_HIGH_SIGNAL_KEYWORDS = [
    "hotel", "lobby", "plaza", "atrium", "mezzanine", "rotunda", "concourse",
    "public open space", "popos", "amenity", "ground floor retail",
    "mixed-use", "flagship", "headquarters", "campus", "branded residence",
    "placemaking", "activation",
    "museum", "gallery", "theater", "theatre", "cultural", "library",
    "university", "hospital", "civic", "terminal", "transit center",
    "station", "waterfront", "landmark", "tower", "high-rise",
    "sanctuary", "nave", "basilica",
    "lab", "laboratory", "life science", "biotech",
]

_LOW_SIGNAL_KEYWORDS = [
    "warehouse", "distribution", "self-storage", "parking structure",
    "parking garage", "gas station", "car wash", "cell tower", "antenna",
    "tenant improvement", "interior only", "adu", "accessory dwelling unit",
    "single family", "sfr", "duplex", "mini storage", "utility",
    "senior care", "assisted living", "nursing",
    "fast food", "drive-through", "drive through", "billboard",
    "auto repair",
]

# Never-art keywords -> _is_irrelevant returns True
_NEVER_ART_KEYWORDS = [
    "self-storage", "storage facility", "car wash", "gas station",
    "auto repair", "drive-through", "drive through",
]

# C. PERMIT TYPE WEIGHT
_TYPE_WEIGHT: dict[PermitType, int] = {
    PermitType.NEW_CONSTRUCTION: 2,
    PermitType.ADDITION:         1,
    PermitType.MAJOR_RENOVATION: 1,
    PermitType.OTHER:            0,
    PermitType.DEMOLITION:       0,
}

# D. STATUS WEIGHT
_STATUS_WEIGHT: dict[PermitStatus, int] = {
    PermitStatus.UNDER_REVIEW: 1,
    PermitStatus.SUBMITTED:    1,
    PermitStatus.APPROVED:     1,
    PermitStatus.ISSUED:       1,
    PermitStatus.FINAL:        0,
    PermitStatus.EXPIRED:      0,
}

# E. VALUATION THRESHOLDS
_VALUATION_NONE_FLOOR = 2_000_000                 # below this, no relevance
_VALUATION_MEDIUM_FLOOR = 10_000_000              # general commercial
_VALUATION_HIGH_FLOOR = 25_000_000                # general high
_VALUATION_HOTEL_HIGH_FLOOR = 15_000_000          # hotels
_VALUATION_HEALTHCARE_HIGH_FLOOR = 20_000_000     # healthcare
_VALUATION_CULTURAL_HIGH_FLOOR = 20_000_000       # cultural + educational
_VALUATION_PUBLIC_HIGH_FLOOR = 5_000_000          # strong-ordinance public
_VALUATION_AIRPORT_HIGH_FLOOR = 50_000_000        # airport/transit
_VALUATION_LIFESCI_HIGH_FLOOR = 75_000_000        # life sciences
_VALUATION_LANDMARK = 50_000_000                  # auto-qualifies for High

# F. SCORE THRESHOLDS for relevance levels
_HIGH_THRESHOLD = 6
_MEDIUM_THRESHOLD = 3

# Square footage bands
_SQ_FT_BANDS = [
    (200_000, 2),
    (50_000,  1),
    (5_000,   0),
    (0,      -1),
]

# Occupancy -> ordinance project types mapping
_OCCUPANCY_TO_ORDINANCE_TYPES: dict[OccupancyType, list[str]] = {
    OccupancyType.COMMERCIAL:         ["Commercial", "Office", "Hotel"],
    OccupancyType.RESIDENTIAL_MULTI:  ["Apartment", "Mixed-Use"],
    OccupancyType.MIXED_USE:          ["Mixed-Use", "Commercial"],
    OccupancyType.CIVIC:              ["Public Capital Projects"],
    OccupancyType.EDUCATIONAL:        ["Commercial"],
    OccupancyType.INDUSTRIAL:         ["Industrial"],
    OccupancyType.RESIDENTIAL_SINGLE: [],
    OccupancyType.OTHER:              ["Commercial"],
}


# ── Keyword and owner helpers ────────────────────────────────────────────────

def _keyword_score(description: str) -> tuple[int, list[str]]:
    """
    Scan work description for art-commissioning signal keywords.
    Returns (score_delta, matched_high_signal_keywords).
    High-signal: +1 each, capped at +3.
    Low-signal: -2 each, uncapped.
    """
    if not description:
        return 0, []
    desc_lower = description.lower()
    matched: list[str] = []
    high_delta = 0
    low_delta = 0
    for kw in _HIGH_SIGNAL_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", desc_lower):
            matched.append(kw)
            high_delta += 1
    for kw in _LOW_SIGNAL_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", desc_lower):
            low_delta -= 2
    return min(3, high_delta) + low_delta, matched


def _is_hotel_keyword(description: str) -> bool:
    """Check if description mentions hotel."""
    if not description:
        return False
    return bool(re.search(r"\bhotel\b", description.lower()))


def _is_airport_transit(permit: CanonicalPermit) -> bool:
    """Detect airport/transit typology from description or owner."""
    desc = (permit.project_description or "").lower()
    airport_kws = ["airport", "terminal", "concourse", "airfield", "runway"]
    transit_kws = ["transit center", "transit station", "rail station", "metro station"]
    for kw in airport_kws + transit_kws:
        if re.search(r"\b" + re.escape(kw) + r"\b", desc):
            return True
    candidate = " ".join(
        part for part in [permit.owner_name, permit.applicant_name] if part
    ).lower()
    for pattern in _OWNER_PATTERNS.get("airport_transit_patterns", []):
        if pattern.lower() in candidate:
            return True
    return False


def _is_life_sciences(permit: CanonicalPermit) -> bool:
    """Detect life sciences typology from description or owner."""
    desc = (permit.project_description or "").lower()
    ls_kws = ["life science", "biotech", "pharmaceutical", "research campus",
              "laboratory", "lab building"]
    for kw in ls_kws:
        if re.search(r"\b" + re.escape(kw) + r"\b", desc):
            return True
    candidate = " ".join(
        part for part in [permit.owner_name, permit.applicant_name] if part
    ).lower()
    ls_owner_kws = ["alexandria", "biomed", "breakthrough properties", "genentech"]
    for kw in ls_owner_kws:
        if kw in candidate:
            return True
    return False


def _is_healthcare(permit: CanonicalPermit) -> bool:
    """Detect healthcare typology from description or owner."""
    desc = (permit.project_description or "").lower()
    if re.search(r"\bhospital\b", desc):
        return True
    if re.search(r"\bmedical center\b", desc):
        return True
    candidate = " ".join(
        part for part in [permit.owner_name, permit.applicant_name] if part
    ).lower()
    for pattern in _OWNER_PATTERNS.get("healthcare_system_patterns", []):
        if pattern.lower() in candidate:
            return True
    return False


def _owner_score(permit: CanonicalPermit) -> tuple[int, list[str], bool, bool, bool]:
    """
    Score based on owner/applicant name matching against known patterns.
    Returns (score_delta, reasons, is_hotel_owner, is_healthcare_owner, is_airport_owner).
    """
    candidate = " ".join(
        part for part in [permit.owner_name, permit.applicant_name] if part
    ).lower()
    if not candidate:
        return 0, [], False, False, False

    score = 0
    reasons: list[str] = []
    is_hotel_owner = False
    is_healthcare_owner = False
    is_airport_owner = False

    # Major developer match
    for pattern in _OWNER_PATTERNS.get("developer_patterns", []):
        if pattern.lower() in candidate:
            score += 2
            reasons.append(f"Major developer ({pattern.title()}) — track record of commissioning art.")
            break

    # Hotel brand match
    for pattern in _OWNER_PATTERNS.get("hotel_brand_patterns", []):
        if pattern.lower() in candidate:
            score += 2
            is_hotel_owner = True
            reasons.append(f"Hotel brand ({pattern.title()}) — hotels are strong art commissioning typology.")
            break

    # Healthcare system match
    for pattern in _OWNER_PATTERNS.get("healthcare_system_patterns", []):
        if pattern.lower() in candidate:
            score += 2
            is_healthcare_owner = True
            reasons.append(f"Healthcare system ({pattern.title()}) — healthcare campuses reliably commission art.")
            break

    # Airport/transit match
    for pattern in _OWNER_PATTERNS.get("airport_transit_patterns", []):
        if pattern.lower() in candidate:
            score += 2
            is_airport_owner = True
            reasons.append(f"Airport/transit authority ({pattern.title()}) — major infrastructure with public art programs.")
            break

    # Cultural institution match
    for pattern in _OWNER_PATTERNS.get("cultural_institution_patterns", []):
        if pattern.lower() in candidate:
            score += 2
            reasons.append(f"Cultural institution ({pattern.title()}) — strong art commissioning tradition.")
            break

    # Cultural keywords (generic)
    if not any("Cultural" in r for r in reasons):
        for kw in _OWNER_PATTERNS.get("cultural_keywords", []):
            if kw.lower() in candidate:
                score += 1
                reasons.append("Cultural institution owner — strong art commissioning tradition.")
                break

    # Tech company match
    for pattern in _OWNER_PATTERNS.get("tech_company_patterns", []):
        if pattern.lower() in candidate:
            score += 1
            reasons.append(f"Major tech company ({pattern.title()}) — campus/HQ projects often include art programs.")
            break

    return score, reasons, is_hotel_owner, is_healthcare_owner, is_airport_owner


def _sqft_score(raw_data: dict) -> tuple[int, Optional[str]]:
    """Score based on square footage when available."""
    raw = (
        raw_data.get("square_footage")
        or raw_data.get("sqft")
        or raw_data.get("sq_ft")
    )
    if not raw:
        return 0, None
    try:
        sqft = float(str(raw).strip().replace(",", ""))
    except (ValueError, TypeError):
        return 0, None
    for threshold, weight in _SQ_FT_BANDS:
        if sqft >= threshold:
            if weight > 0:
                return weight, f"{sqft:,.0f} sq ft — significant development scale."
            elif weight < 0:
                return weight, f"{sqft:,.0f} sq ft — small project; lower art commissioning potential."
            else:
                return 0, None
    return 0, None


def _outreach_timing(permit: CanonicalPermit) -> str:
    """Translate permit status into outreach timing language."""
    raw_status = (permit.raw_data.get("status_desc") or
                  permit.raw_data.get("status") or "")
    if raw_status == "Ready to Issue":
        return "Act now — permit imminent"
    if permit.permit_status in (PermitStatus.UNDER_REVIEW, PermitStatus.SUBMITTED):
        return "Early — in plan review"
    if permit.permit_status == PermitStatus.APPROVED:
        return "Mid — approved, pre-construction"
    if permit.permit_status in (PermitStatus.ISSUED, PermitStatus.FINAL):
        return "Late — construction may have started"
    return "Early — in plan review"


# ── Output types ─────────────────────────────────────────────────────────────

class RelevanceLevel(str, Enum):
    HIGH   = "High"
    MEDIUM = "Medium"
    LOW    = "Low"
    NONE   = "None"


@dataclass
class OrdMatchResult:
    """Result of checking one ordinance against one permit."""
    triggered: bool
    ordinance_name: str
    ordinance_percentage: float
    art_budget_low: Optional[float]
    art_budget_high: Optional[float]
    reason: str
    practical_strength: str = "strong"   # "strong" or "weak"


@dataclass
class ScoredPermit:
    """A CanonicalPermit enriched with art commissioning intelligence."""
    permit: CanonicalPermit
    ordinance_triggered: bool
    ordinance_dependent: bool
    ordinance_name: Optional[str]
    ordinance_match_reason: str
    art_budget_low: Optional[float]
    art_budget_high: Optional[float]
    art_budget_display: str
    budget_basis: str
    relevance: RelevanceLevel
    relevance_reasons: list[str]
    opportunity_stage: str
    keyword_signals: list[str]
    scoring_factors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = self.permit.to_dict()
        d.update({
            "ordinance_triggered":  self.ordinance_triggered,
            "ordinance_dependent":  self.ordinance_dependent,
            "ordinance_name":       self.ordinance_name,
            "art_budget_display":   self.art_budget_display,
            "budget_basis":         self.budget_basis,
            "relevance":            self.relevance.value,
            "relevance_reasons":    self.relevance_reasons,
            "opportunity_stage":    self.opportunity_stage,
            "keyword_signals":      self.keyword_signals,
            "scoring_factors":      self.scoring_factors,
        })
        return d


# ── Ordinance loader ─────────────────────────────────────────────────────────

def load_ordinances(path: Optional[str] = None) -> list[dict]:
    if path is None:
        path = os.path.join(
            os.path.dirname(__file__),
            "ordinances", "data", "percent_for_art.json"
        )
    with open(path, "r") as f:
        return json.load(f)


# ── Core scoring ─────────────────────────────────────────────────────────────

def score_permit(
    permit: CanonicalPermit,
    ordinances: list[dict],
) -> ScoredPermit:
    """Score a single CanonicalPermit for art commissioning relevance."""

    # Step 1: irrelevance check
    if _is_irrelevant(permit):
        ord_result = _match_ordinances(permit, ordinances)
        budget_display, budget_basis = _format_budget(permit, ord_result)
        return ScoredPermit(
            permit=permit,
            ordinance_triggered=ord_result.triggered,
            ordinance_dependent=False,
            ordinance_name=ord_result.ordinance_name if ord_result.triggered else None,
            ordinance_match_reason=ord_result.reason,
            art_budget_low=ord_result.art_budget_low,
            art_budget_high=ord_result.art_budget_high,
            art_budget_display=budget_display,
            budget_basis=budget_basis,
            relevance=RelevanceLevel.NONE,
            relevance_reasons=["Project type or status does not support art commissioning."],
            opportunity_stage=_outreach_timing(permit),
            keyword_signals=[],
            scoring_factors=["irrelevant_typology"],
        )

    # Step 2: ordinance matching
    ord_result = _match_ordinances(permit, ordinances)

    # Step 3: compute multi-factor score
    score, reasons, keyword_signals, scoring_factors = _compute_score(permit, ord_result)

    # Step 4: determine relevance level with valuation floors
    relevance = _determine_relevance(permit, score, ord_result, keyword_signals)

    # Step 5: ordinance dependency
    ordinance_dependent = _compute_ordinance_dependent(
        permit, ord_result, score, relevance, keyword_signals
    )

    # Step 6: budget display
    budget_display, budget_basis = _format_budget(permit, ord_result)

    return ScoredPermit(
        permit=permit,
        ordinance_triggered=ord_result.triggered,
        ordinance_dependent=ordinance_dependent,
        ordinance_name=ord_result.ordinance_name if ord_result.triggered else None,
        ordinance_match_reason=ord_result.reason,
        art_budget_low=ord_result.art_budget_low,
        art_budget_high=ord_result.art_budget_high,
        art_budget_display=budget_display,
        budget_basis=budget_basis,
        relevance=relevance,
        relevance_reasons=reasons,
        opportunity_stage=_outreach_timing(permit),
        keyword_signals=keyword_signals,
        scoring_factors=scoring_factors,
    )


def score_permits(
    permits: list[CanonicalPermit],
    ordinances: Optional[list[dict]] = None,
) -> list[ScoredPermit]:
    """Score a list of permits. Loads ordinances from disk if not provided."""
    if ordinances is None:
        ordinances = load_ordinances()
    return [score_permit(p, ordinances) for p in permits]


# ── Irrelevance check ────────────────────────────────────────────────────────

def _is_irrelevant(permit: CanonicalPermit) -> bool:
    """True for permits where art commissioning is implausible."""
    if permit.permit_type == PermitType.DEMOLITION:
        return True
    if permit.permit_status == PermitStatus.EXPIRED:
        return True
    if permit.occupancy_type in _IRRELEVANT_OCCUPANCY:
        return True
    desc_lower = (permit.project_description or "").lower()
    for kw in _NEVER_ART_KEYWORDS:
        if re.search(r"\b" + re.escape(kw) + r"\b", desc_lower):
            return True
    return False


# ── Multi-factor scoring ─────────────────────────────────────────────────────

def _compute_score(
    permit: CanonicalPermit,
    ord_result: OrdMatchResult,
) -> tuple[int, list[str], list[str], list[str]]:
    """
    Compute composite score from typology, owner, keywords, ordinance, etc.
    Returns (score, reasons, keyword_signals, scoring_factors).
    """
    score = 0
    reasons: list[str] = []
    scoring_factors: list[str] = []
    keyword_signals: list[str] = []

    # A. TYPOLOGY — detect special typologies first
    is_hotel = _is_hotel_keyword(permit.project_description)
    is_airport = _is_airport_transit(permit)
    is_lifesci = _is_life_sciences(permit)
    is_healthcare = _is_healthcare(permit)

    if is_airport:
        score += 3
        reasons.append("Airport/transit project — major infrastructure with dedicated public art programs.")
        scoring_factors.append("typology:airport_transit:+3")
    elif is_hotel:
        score += 3
        reasons.append("Hotel project — strong typology for art commissioning regardless of ordinance status.")
        scoring_factors.append("typology:hotel:+3")
    elif is_healthcare:
        score += 3
        reasons.append("Healthcare facility — hospitals and medical centers reliably commission healing arts.")
        scoring_factors.append("typology:healthcare:+3")
    elif is_lifesci:
        score += 1
        reasons.append("Life sciences facility — research campuses increasingly include public-facing art.")
        scoring_factors.append("typology:life_sciences:+1")
    else:
        typology_bump = _TYPOLOGY_BUMP.get(permit.occupancy_type, 0)
        if typology_bump > 0:
            score += typology_bump
            if permit.occupancy_type == OccupancyType.CIVIC:
                reasons.append("Civic/public facility — strong art commissioning tradition.")
            elif permit.occupancy_type == OccupancyType.EDUCATIONAL:
                reasons.append("Educational institution — universities and schools often commission art.")
            elif permit.occupancy_type == OccupancyType.MIXED_USE:
                reasons.append("Mixed-use development with public-facing spaces.")
            elif permit.occupancy_type == OccupancyType.COMMERCIAL:
                reasons.append("Commercial project — art commissioning potential depends on scale and program.")
            scoring_factors.append(f"typology:{permit.occupancy_type.value}:+{typology_bump}")

    # B. OWNER TYPE
    owner_delta, owner_reasons, is_hotel_owner, is_healthcare_owner, is_airport_owner = _owner_score(permit)
    if owner_delta > 0:
        score += owner_delta
        reasons.extend(owner_reasons)
        scoring_factors.append(f"owner:+{owner_delta}")
        if is_hotel_owner and not is_hotel:
            is_hotel = True
            score += 2
            scoring_factors.append("owner_hotel_upgrade:+2")
        if is_healthcare_owner and not is_healthcare:
            is_healthcare = True
        if is_airport_owner and not is_airport:
            is_airport = True

    # Check public-sector owner for ordinance purposes
    public_patterns = permit.raw_data.get("public_sector_owner_patterns", [])
    is_public_owner = _matches_public_sector_owner(permit, public_patterns)
    if is_public_owner:
        score += 2
        reasons.append("Public-sector owner — percent-for-art requirements likely apply.")
        scoring_factors.append("owner:public_sector:+2")

    # C. KEYWORD SIGNALS
    kw_delta, matched_kws = _keyword_score(permit.project_description)
    keyword_signals = matched_kws
    score += kw_delta
    if matched_kws:
        reasons.append(f"Work description includes: {', '.join(matched_kws)}.")
        scoring_factors.append(f"keywords:+{min(3, len(matched_kws))}")
    if kw_delta < 0:
        scoring_factors.append(f"negative_keywords:{kw_delta}")

    # D. PERMIT TYPE
    type_w = _TYPE_WEIGHT.get(permit.permit_type, 0)
    score += type_w
    if permit.permit_type == PermitType.NEW_CONSTRUCTION:
        reasons.append("New construction — art decisions happen earliest in this phase.")
        scoring_factors.append("permit_type:new:+2")
    elif permit.permit_type in (PermitType.MAJOR_RENOVATION, PermitType.ADDITION):
        reasons.append("Renovation or addition — art commissioning still possible.")
        scoring_factors.append("permit_type:renovation:+1")

    # E. STATUS
    status_w = _STATUS_WEIGHT.get(permit.permit_status, 0)
    score += status_w
    if permit.permit_status == PermitStatus.FINAL:
        reasons.append("Near completion — late stage, window may be closing.")
    if status_w > 0:
        scoring_factors.append(f"status:+{status_w}")

    # F. SQUARE FOOTAGE
    sqft_delta, sqft_reason = _sqft_score(permit.raw_data)
    score += sqft_delta
    if sqft_reason:
        reasons.append(sqft_reason)
        scoring_factors.append(f"sqft:{sqft_delta:+d}")

    # G. ORDINANCE (softened — strong vs weak)
    if ord_result.triggered:
        if ord_result.practical_strength == "strong":
            score += 2
            reasons.append(
                f"Subject to {ord_result.ordinance_name} — "
                "percent-for-art requirement actively drives commissioning in this city."
            )
            scoring_factors.append("ordinance:strong:+2")
        else:
            score += 1
            reasons.append(
                f"Subject to {ord_result.ordinance_name} — "
                "legal requirement exists but has historically driven few actual commissions."
            )
            scoring_factors.append("ordinance:weak:+1")

    # H. VALUATION (modest contribution)
    if permit.valuation:
        if permit.valuation >= 50_000_000:
            score += 2
            reasons.append(
                f"${permit.valuation/1_000_000:.0f}M valuation — "
                "large-scale landmark project; trophy developments in this tier typically include public-facing art."
            )
            scoring_factors.append("valuation:landmark:+2")
        elif permit.valuation >= 20_000_000:
            score += 1
            reasons.append(
                f"${permit.valuation/1_000_000:.0f}M valuation — "
                "large project, significant art budget likely."
            )
            scoring_factors.append("valuation:large:+1")
        elif permit.valuation >= 10_000_000:
            reasons.append(
                f"${permit.valuation/1_000_000:.1f}M valuation — "
                "mid-scale project."
            )

    return score, reasons, keyword_signals, scoring_factors


def _determine_relevance(
    permit: CanonicalPermit,
    score: int,
    ord_result: OrdMatchResult,
    keyword_signals: list[str],
) -> RelevanceLevel:
    """Map composite score to relevance level with valuation floors."""
    val = permit.valuation or 0

    # Hard floor: below $2M is never relevant
    if val < _VALUATION_NONE_FLOOR and val > 0:
        return RelevanceLevel.NONE
    if val == 0 and not ord_result.triggered:
        # Unknown valuation without ordinance — cap at Medium
        if score >= _MEDIUM_THRESHOLD:
            return RelevanceLevel.MEDIUM
        return RelevanceLevel.NONE

    is_hotel = _is_hotel_keyword(permit.project_description)
    is_airport = _is_airport_transit(permit)
    is_lifesci = _is_life_sciences(permit)
    is_healthcare = _is_healthcare(permit)
    is_strong_public = (
        ord_result.triggered
        and ord_result.practical_strength == "strong"
    )

    # HIGH determination
    if score >= _HIGH_THRESHOLD:
        # Apply valuation floors by typology (most specific first)
        if is_strong_public and val >= _VALUATION_PUBLIC_HIGH_FLOOR:
            return RelevanceLevel.HIGH
        if is_hotel and val >= _VALUATION_HOTEL_HIGH_FLOOR:
            return RelevanceLevel.HIGH
        if is_healthcare and val >= _VALUATION_HEALTHCARE_HIGH_FLOOR:
            return RelevanceLevel.HIGH
        if is_airport and val >= _VALUATION_AIRPORT_HIGH_FLOOR:
            return RelevanceLevel.HIGH
        if is_lifesci and val >= _VALUATION_LIFESCI_HIGH_FLOOR:
            return RelevanceLevel.HIGH
        if permit.occupancy_type in (OccupancyType.CIVIC, OccupancyType.EDUCATIONAL):
            if val >= _VALUATION_CULTURAL_HIGH_FLOOR:
                return RelevanceLevel.HIGH
        if val >= _VALUATION_LANDMARK:
            return RelevanceLevel.HIGH
        if val >= _VALUATION_HIGH_FLOOR:
            return RelevanceLevel.HIGH
        # Score qualifies but valuation too low for High -> Medium
        return RelevanceLevel.MEDIUM

    # MEDIUM determination
    if score >= _MEDIUM_THRESHOLD:
        if val >= _VALUATION_NONE_FLOOR:
            return RelevanceLevel.MEDIUM
        return RelevanceLevel.NONE

    return RelevanceLevel.NONE


def _compute_ordinance_dependent(
    permit: CanonicalPermit,
    ord_result: OrdMatchResult,
    score: int,
    relevance: RelevanceLevel,
    keyword_signals: list[str],
) -> bool:
    """True when removing the ordinance bonus would drop below current relevance."""
    if not ord_result.triggered:
        return False

    ord_bonus = 2 if ord_result.practical_strength == "strong" else 1
    score_sans_ord = score - ord_bonus

    if relevance == RelevanceLevel.HIGH:
        return score_sans_ord < _HIGH_THRESHOLD
    if relevance == RelevanceLevel.MEDIUM:
        return score_sans_ord < _MEDIUM_THRESHOLD
    return False


# ── Ordinance matching ───────────────────────────────────────────────────────

def _match_ordinances(permit: CanonicalPermit, ordinances: list[dict]) -> OrdMatchResult:
    """Find the best-matching triggered ordinance for this permit."""
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

    # Prefer strong ordinances over weak ones
    for ord_data in sorted(city_ordinances, key=lambda o: o.get("practical_strength", "strong") == "strong", reverse=True):
        result = _check_ordinance(permit, ord_data)
        if result.triggered:
            return result

    return _check_ordinance(permit, city_ordinances[0])


def _matches_public_sector_owner(permit: CanonicalPermit, patterns: list[str]) -> bool:
    """Return True when the permit owner or applicant matches a public-sector pattern."""
    if not patterns:
        return False
    candidate = " ".join(
        part for part in [permit.owner_name, permit.applicant_name] if part
    ).lower()
    if not candidate:
        return False
    for pattern in patterns:
        if pattern.lower() in candidate:
            return True
    return False


def _check_ordinance(permit: CanonicalPermit, ord_data: dict) -> OrdMatchResult:
    """Check whether a single ordinance applies to this permit."""
    name = ord_data.get("ordinance_name", "Unknown Ordinance")
    pct = ord_data.get("percentage", 0.0)
    strength = ord_data.get("practical_strength", "strong")

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
                practical_strength=strength,
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
                practical_strength=strength,
            )

    # Project type check
    applicable_types: list[str] = ord_data.get("project_types", [])
    occupancy_types_for_permit = _OCCUPANCY_TO_ORDINANCE_TYPES.get(
        permit.occupancy_type, []
    )
    type_match = any(t in applicable_types for t in occupancy_types_for_permit)

    public_patterns = permit.raw_data.get("public_sector_owner_patterns", [])
    public_owner_match = False
    if public_patterns and "Public Capital Projects" in applicable_types:
        public_owner_match = _matches_public_sector_owner(permit, public_patterns)
        if not type_match and not public_owner_match:
            return OrdMatchResult(
                triggered=False,
                ordinance_name=name,
                ordinance_percentage=pct,
                art_budget_low=None,
                art_budget_high=None,
                reason=(
                    "Public sector owner/applicant not identified — "
                    f"{name} applies only to city or public authority projects."
                ),
                practical_strength=strength,
            )

    if not type_match and not public_owner_match:
        return OrdMatchResult(
            triggered=False,
            ordinance_name=name,
            ordinance_percentage=pct,
            art_budget_low=None,
            art_budget_high=None,
            reason=(
                f"{permit.occupancy_type.value} projects do not trigger {name}."
            ),
            practical_strength=strength,
        )

    # Triggered
    budget_low = permit.valuation * pct * 0.8 if permit.valuation else None
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
        practical_strength=strength,
    )


# ── Budget formatting ────────────────────────────────────────────────────────

def _format_budget(
    permit: CanonicalPermit,
    ord_result: OrdMatchResult,
) -> tuple[str, str]:
    """Return (display_string, basis_sentence) for the art budget estimate."""
    # Strong ordinance: use actual rate
    if (
        ord_result.triggered
        and ord_result.practical_strength == "strong"
        and ord_result.art_budget_low is not None
    ):
        low = ord_result.art_budget_low
        high = ord_result.art_budget_high or low
        display = f"${_fmt_k(low)}–${_fmt_k(high)}"
        basis = (
            f"{ord_result.ordinance_percentage * 100:.0f}% of "
            f"${permit.valuation:,.0f} construction cost per "
            f"{ord_result.ordinance_name}."
        )
        return display, basis

    # Weak ordinance: use heuristic, don't derive from ordinance rate
    if (
        ord_result.triggered
        and ord_result.practical_strength == "weak"
        and permit.valuation
        and permit.valuation >= 5_000_000
    ):
        low = permit.valuation * 0.005
        high = permit.valuation * 0.010
        display = f"${_fmt_k(low)}–${_fmt_k(high)}"
        basis = (
            f"Approximately 0.5%–1% of valuation; {ord_result.ordinance_name} "
            "applies but actual commissioning varies widely."
        )
        return display, basis

    # No ordinance — heuristic range
    if permit.valuation and permit.valuation >= 5_000_000:
        low = permit.valuation * 0.005
        high = permit.valuation * 0.015
        display = f"${_fmt_k(low)}–${_fmt_k(high)}"
        basis = (
            "Estimated 0.5%–1.5% of construction cost; "
            "no applicable ordinance confirmed."
        )
        return display, basis

    return "", "Valuation below threshold or unknown."


def _fmt_k(value: float) -> str:
    """Format a dollar value compactly: $1,250,000 -> '1.2M', $75,000 -> '75K'."""
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2g}M"
    if value >= 1_000:
        return f"{value / 1_000:.0f}K"
    return f"{value:.0f}"
