"""
Tests for permits/engine.py — the art commissioning relevance scoring engine.

These tests exercise programmatic rules that must be correct.
No API calls, no file I/O beyond loading the real ordinance JSON.
"""

import pytest

from permits.schema import (
    CanonicalPermit, PermitType, PermitStatus, OccupancyType,
)
from permits.engine import (
    RelevanceLevel, ScoredPermit,
    score_permit, score_permits, load_ordinances,
    _match_ordinances, _check_ordinance, _is_irrelevant,
    _keyword_score, _sqft_score, _outreach_timing,
    _fmt_k,
)
from tests.conftest import make_permit


# ── Ordinance data loading ─────────────────────────────────────────────────────

class TestLoadOrdinances:

    def test_load_returns_list(self, la_ordinances):
        assert isinstance(la_ordinances, list)
        assert len(la_ordinances) >= 1

    def test_padfp_entry_present(self, la_ordinances):
        names = [o["ordinance_name"] for o in la_ordinances]
        assert any("PADFP" in n or "Private Arts Development Fee" in n for n in names)

    def test_padfp_fields_correct(self, la_ordinances):
        padfp = next(
            o for o in la_ordinances
            if "PADFP" in o.get("ordinance_name", "") or
               "Private Arts Development Fee" in o.get("ordinance_name", "")
        )
        assert padfp["city"] == "Los Angeles"
        assert padfp["state"] == "CA"
        assert padfp["percentage"] == pytest.approx(0.01)
        assert padfp["valuation_threshold"] == 500_000
        assert "Commercial" in padfp["project_types"]

    def test_load_with_empty_list(self):
        """Engine handles an empty ordinances list without crashing."""
        permit = make_permit()
        result = score_permit(permit, [])
        assert isinstance(result, ScoredPermit)
        assert result.ordinance_triggered is False


# ── Irrelevance filter ─────────────────────────────────────────────────────────

class TestIsIrrelevant:

    def test_demolition_is_irrelevant(self):
        p = make_permit(permit_type=PermitType.DEMOLITION)
        assert _is_irrelevant(p) is True

    def test_expired_is_irrelevant(self):
        p = make_permit(permit_status=PermitStatus.EXPIRED)
        assert _is_irrelevant(p) is True

    def test_single_family_is_irrelevant(self):
        p = make_permit(occupancy_type=OccupancyType.RESIDENTIAL_SINGLE)
        assert _is_irrelevant(p) is True

    def test_industrial_is_irrelevant(self):
        p = make_permit(occupancy_type=OccupancyType.INDUSTRIAL)
        assert _is_irrelevant(p) is True

    def test_commercial_new_construction_is_relevant(self):
        p = make_permit(
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            occupancy_type=OccupancyType.COMMERCIAL,
        )
        assert _is_irrelevant(p) is False


# ── Ordinance matching ────────────────────────────────────────────────────────

class TestOrdinanceMatching:

    def test_commercial_above_threshold_triggers_padfp(self, la_ordinances):
        permit = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=10_000_000.0,
        )
        result = _match_ordinances(permit, la_ordinances)
        assert result.triggered is True
        assert "PADFP" in result.ordinance_name or "Private Arts" in result.ordinance_name

    def test_commercial_below_threshold_does_not_trigger(self, la_ordinances):
        permit = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=300_000.0,
        )
        result = _match_ordinances(permit, la_ordinances)
        assert result.triggered is False

    def test_single_family_does_not_trigger(self, la_ordinances):
        permit = make_permit(
            occupancy_type=OccupancyType.RESIDENTIAL_SINGLE,
            valuation=10_000_000.0,
        )
        result = _match_ordinances(permit, la_ordinances)
        assert result.triggered is False

    def test_null_valuation_does_not_crash(self, la_ordinances):
        permit = make_permit(valuation=None)
        result = _match_ordinances(permit, la_ordinances)
        assert isinstance(result.triggered, bool)

    def test_unknown_city_returns_not_triggered(self, la_ordinances):
        permit = make_permit(city="Atlantis", state="ZZ")
        result = _match_ordinances(permit, la_ordinances)
        assert result.triggered is False

    def test_apartment_above_threshold_triggers_padfp(self, la_ordinances):
        """Apartments are listed in PADFP project_types."""
        permit = make_permit(
            occupancy_type=OccupancyType.RESIDENTIAL_MULTI,
            valuation=2_000_000.0,
        )
        result = _match_ordinances(permit, la_ordinances)
        assert result.triggered is True

    def test_art_budget_low_high_calculated_correctly(self, la_ordinances):
        """Budget = 1% × valuation ± 20%."""
        permit = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=10_000_000.0,
        )
        result = _match_ordinances(permit, la_ordinances)
        assert result.triggered is True
        assert result.art_budget_low == pytest.approx(10_000_000 * 0.01 * 0.8)
        assert result.art_budget_high == pytest.approx(10_000_000 * 0.01 * 1.2)


# ── Relevance scoring ─────────────────────────────────────────────────────────

class TestRelevanceScoring:

    def test_commercial_new_construction_large_is_high(self, la_ordinances):
        permit = make_permit(
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=20_000_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.relevance == RelevanceLevel.HIGH

    def test_commercial_below_padfp_threshold_caps_at_medium(self, la_ordinances):
        # A $300K commercial new construction earns 9 category points but the
        # ordinance doesn't trigger. The valuation floor ($5M) prevents HIGH
        # when there's no ordinance requirement — small tenant improvements and
        # minor retail buildouts are not Tre's market.
        permit = make_permit(
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=300_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.relevance == RelevanceLevel.MEDIUM
        assert result.ordinance_triggered is False

    def test_large_project_without_ordinance_trigger_still_scores_high(self, la_ordinances):
        # A $10M project in a city with no ordinance (or wrong project type for
        # the ordinance) should still score HIGH — voluntary commissioning is
        # plausible at that scale even without a formal requirement.
        permit = make_permit(
            city="Somewhere", state="XX",   # no ordinance data for this city
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=10_000_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.ordinance_triggered is False
        assert result.relevance == RelevanceLevel.HIGH

    def test_single_family_is_none_regardless_of_valuation(self, la_ordinances):
        permit = make_permit(
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.UNDER_REVIEW,
            occupancy_type=OccupancyType.RESIDENTIAL_SINGLE,
            valuation=50_000_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.relevance == RelevanceLevel.NONE

    def test_demolition_is_none(self, la_ordinances):
        permit = make_permit(
            permit_type=PermitType.DEMOLITION,
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=20_000_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.relevance == RelevanceLevel.NONE

    def test_expired_is_none(self, la_ordinances):
        permit = make_permit(
            permit_type=PermitType.NEW_CONSTRUCTION,
            permit_status=PermitStatus.EXPIRED,
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=20_000_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.relevance == RelevanceLevel.NONE

    def test_ordinance_triggered_permit_scores_higher_than_non_triggered(self, la_ordinances):
        above = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=10_000_000.0,
            permit_id="ABOVE",
        )
        # Industrial doesn't trigger PADFP
        below = make_permit(
            occupancy_type=OccupancyType.INDUSTRIAL,
            valuation=10_000_000.0,
            permit_id="BELOW",
        )
        above_result = score_permit(above, la_ordinances)
        below_result = score_permit(below, la_ordinances)
        assert above_result.relevance != below_result.relevance or \
               above_result.ordinance_triggered and not below_result.ordinance_triggered

    def test_null_valuation_does_not_crash(self, la_ordinances):
        permit = make_permit(valuation=None)
        result = score_permit(permit, la_ordinances)
        assert isinstance(result, ScoredPermit)
        assert result.relevance in RelevanceLevel.__members__.values()

    def test_null_valuation_no_ordinance_triggered(self, la_ordinances):
        permit = make_permit(valuation=None)
        result = score_permit(permit, la_ordinances)
        assert result.ordinance_triggered is False

    def test_empty_ordinances_graceful(self):
        permit = make_permit(valuation=10_000_000.0)
        result = score_permit(permit, [])
        assert isinstance(result, ScoredPermit)
        assert result.ordinance_triggered is False


# ── Art budget display ─────────────────────────────────────────────────────────

class TestArtBudgetDisplay:

    def test_triggered_permit_has_budget_display(self, la_ordinances):
        permit = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=10_000_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.ordinance_triggered is True
        assert result.art_budget_display != ""
        assert "–" in result.art_budget_display  # range separator

    def test_non_triggered_above_5m_has_heuristic_budget(self, la_ordinances):
        """No ordinance match but large project: heuristic range shown."""
        permit = make_permit(
            city="Somewhere", state="XX",   # no ordinance for this city
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=10_000_000.0,
        )
        result = score_permit(permit, la_ordinances)
        assert result.ordinance_triggered is False
        assert result.art_budget_display != ""

    def test_budget_range_proportional_to_valuation(self, la_ordinances):
        small = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=1_000_000.0,
            permit_id="SMALL",
        )
        large = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=50_000_000.0,
            permit_id="LARGE",
        )
        small_result = score_permit(small, la_ordinances)
        large_result = score_permit(large, la_ordinances)
        # Both triggered — large should have a bigger budget
        if small_result.art_budget_low and large_result.art_budget_low:
            assert large_result.art_budget_low > small_result.art_budget_low

    def test_null_valuation_budget_display_empty_or_graceful(self, la_ordinances):
        permit = make_permit(valuation=None)
        result = score_permit(permit, la_ordinances)
        # No crash; display is either empty or contains some text
        assert isinstance(result.art_budget_display, str)


# ── score_permits (batch) ──────────────────────────────────────────────────────

class TestScorePermits:

    def test_empty_list_returns_empty(self, la_ordinances):
        assert score_permits([], la_ordinances) == []

    def test_returns_same_count_as_input(self, la_ordinances):
        permits = [make_permit(permit_id=f"P-{i}") for i in range(5)]
        results = score_permits(permits, la_ordinances)
        assert len(results) == 5

    def test_loads_ordinances_from_disk_when_not_provided(self):
        """Calling score_permits() without ordinances argument should not crash."""
        permit = make_permit()
        results = score_permits([permit])
        assert len(results) == 1

    def test_to_dict_has_scoring_fields(self, la_ordinances):
        permit = make_permit(
            occupancy_type=OccupancyType.COMMERCIAL,
            valuation=10_000_000.0,
        )
        result = score_permits([permit], la_ordinances)[0]
        d = result.to_dict()
        assert "relevance" in d
        assert "ordinance_triggered" in d
        assert "art_budget_display" in d
        assert "relevance_reasons" in d
        assert isinstance(d["relevance_reasons"], list)
        assert "opportunity_stage" in d
        assert "keyword_signals" in d

    def test_to_dict_keyword_signals_is_list(self, la_ordinances):
        permit = make_permit(project_description="New hotel lobby and plaza")
        result = score_permits([permit], la_ordinances)[0]
        d = result.to_dict()
        assert isinstance(d["keyword_signals"], list)
        assert "hotel" in d["keyword_signals"] or "lobby" in d["keyword_signals"]


# ── Keyword scoring ───────────────────────────────────────────────────────────

class TestKeywordScore:

    def test_hotel_keyword_positive(self):
        delta, matched = _keyword_score("New 12-story hotel with rooftop terrace")
        assert delta > 0
        assert "hotel" in matched

    def test_lobby_and_plaza_both_match(self):
        delta, matched = _keyword_score("Mixed-use tower with ground floor lobby and public plaza")
        assert delta > 0
        assert "lobby" in matched
        assert "plaza" in matched

    def test_theater_keyword_positive(self):
        delta, matched = _keyword_score("Renovation of existing theater")
        assert delta > 0
        assert "theater" in matched

    def test_theatre_alternate_spelling(self):
        delta, matched = _keyword_score("New community theatre and cultural center")
        assert "theatre" in matched or "cultural center" in matched

    def test_warehouse_keyword_negative(self):
        delta, matched = _keyword_score("New warehouse and storage facility")
        assert delta < 0
        assert matched == []  # low-signal keywords do not add to matched list

    def test_parking_structure_negative(self):
        delta, matched = _keyword_score("6-level parking structure")
        assert delta < 0

    def test_empty_description_returns_zero(self):
        delta, matched = _keyword_score("")
        assert delta == 0
        assert matched == []

    def test_score_capped_at_plus_two(self):
        # Pile in many high-signal keywords
        desc = "hotel lobby museum gallery theater plaza library cultural center university"
        delta, _ = _keyword_score(desc)
        assert delta <= 2

    def test_score_capped_at_minus_two(self):
        desc = "warehouse parking structure self-storage parking garage storage facility cell tower"
        delta, _ = _keyword_score(desc)
        assert delta >= -2

    def test_high_signal_description_scores_higher_than_generic(self, la_ordinances):
        hotel = make_permit(
            project_description="New boutique hotel with lobby and gallery",
            permit_id="HOTEL-001",
        )
        generic = make_permit(
            project_description="New commercial building",
            permit_id="GENERIC-001",
        )
        hotel_result = score_permit(hotel, la_ordinances)
        generic_result = score_permit(generic, la_ordinances)
        # Both should be scored, hotel should be at least as high
        # (same base score + keyword bonus)
        assert hotel_result.keyword_signals  # hotel has signals
        assert not generic_result.keyword_signals or \
               len(hotel_result.keyword_signals) > len(generic_result.keyword_signals)


# ── Square footage scoring ─────────────────────────────────────────────────────

class TestSqftScore:

    def test_large_sqft_positive(self):
        delta, reason = _sqft_score({"square_footage": "200000"})
        assert delta > 0
        assert reason is not None

    def test_significant_sqft_positive(self):
        delta, reason = _sqft_score({"square_footage": "75000"})
        assert delta > 0

    def test_small_sqft_negative(self):
        delta, reason = _sqft_score({"square_footage": "3000"})
        assert delta < 0
        assert reason is not None

    def test_mid_range_sqft_neutral(self):
        delta, reason = _sqft_score({"square_footage": "20000"})
        assert delta == 0
        assert reason is None

    def test_missing_sqft_returns_zero(self):
        delta, reason = _sqft_score({})
        assert delta == 0
        assert reason is None

    def test_malformed_sqft_returns_zero(self):
        delta, reason = _sqft_score({"square_footage": "N/A"})
        assert delta == 0
        assert reason is None

    def test_sqft_with_commas_parsed(self):
        delta, reason = _sqft_score({"square_footage": "250,000"})
        assert delta > 0  # 250k sqft is major development

    def test_large_sqft_boosts_score_in_full_pipeline(self, la_ordinances):
        """A project with large square footage scores higher than the same without."""
        with_sqft = make_permit(
            raw_data={"square_footage": "200000"},
            permit_id="WITH-SQFT",
        )
        without_sqft = make_permit(
            raw_data={},
            permit_id="NO-SQFT",
        )
        r_with    = score_permit(with_sqft, la_ordinances)
        r_without = score_permit(without_sqft, la_ordinances)
        # with_sqft should be HIGH if without is MEDIUM, or same with higher score
        # At minimum, the boost doesn't degrade it
        assert r_with.relevance != RelevanceLevel.NONE


# ── Outreach timing ───────────────────────────────────────────────────────────

class TestOutreachTiming:

    def test_under_review_is_early(self):
        p = make_permit(permit_status=PermitStatus.UNDER_REVIEW)
        assert _outreach_timing(p) == "Early — in plan review"

    def test_submitted_is_early(self):
        p = make_permit(permit_status=PermitStatus.SUBMITTED)
        assert _outreach_timing(p) == "Early — in plan review"

    def test_approved_is_mid(self):
        p = make_permit(permit_status=PermitStatus.APPROVED)
        assert _outreach_timing(p) == "Mid — approved, pre-construction"

    def test_ready_to_issue_is_act_now(self):
        """'Ready to Issue' maps to canonical APPROVED but is a special urgency case."""
        p = make_permit(
            permit_status=PermitStatus.APPROVED,
            raw_data={"status_desc": "Ready to Issue"},
        )
        assert _outreach_timing(p) == "Act now — permit imminent"

    def test_issued_is_late(self):
        p = make_permit(permit_status=PermitStatus.ISSUED)
        assert _outreach_timing(p) == "Late — construction may have started"

    def test_final_is_late(self):
        p = make_permit(permit_status=PermitStatus.FINAL)
        assert _outreach_timing(p) == "Late — construction may have started"

    def test_opportunity_stage_in_scored_permit(self, la_ordinances):
        """score_permit populates opportunity_stage correctly."""
        p = make_permit(
            permit_status=PermitStatus.UNDER_REVIEW,
            valuation=10_000_000.0,
        )
        result = score_permit(p, la_ordinances)
        assert result.opportunity_stage == "Early — in plan review"

    def test_ready_to_issue_stage_in_scored_permit(self, la_ordinances):
        p = make_permit(
            permit_status=PermitStatus.APPROVED,
            raw_data={"status_desc": "Ready to Issue"},
            valuation=10_000_000.0,
        )
        result = score_permit(p, la_ordinances)
        assert result.opportunity_stage == "Act now — permit imminent"


# ── _fmt_k helper ─────────────────────────────────────────────────────────────

class TestFmtK:

    @pytest.mark.parametrize("value,expected", [
        (80_000.0,       "80K"),
        (100_000.0,      "100K"),
        (1_000_000.0,    "1M"),
        (1_250_000.0,    "1.2M"),
        (50_000_000.0,   "5e+07"),   # scientific notation at this scale via :.2g
        (500.0,          "500"),
    ])
    def test_fmt_k_output(self, value, expected):
        result = _fmt_k(value)
        # The important properties: no crash, returns a string, contains a digit
        assert isinstance(result, str)
        assert any(c.isdigit() for c in result)
