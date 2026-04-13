"""
Flask routes for the Permits Intelligence tab.

Blueprint: permits_bp
Routes:
  GET /permits-monitor          → renders permits.html
  GET /api/permits              → returns ScoredPermit records as JSON
  GET /api/permits/metadata     → returns connector metadata
"""

from datetime import date

from flask import Blueprint, request, jsonify, render_template

from permits.connectors.base import ConnectorFilters
from permits.connectors.cities.los_angeles import la_connector
from permits.engine import score_permits, RelevanceLevel

permits_bp = Blueprint("permits", __name__)


def _budget_sort_key(sp) -> float:
    """
    Best estimate of the art budget value for sorting purposes.
    Uses the ordinance-derived lower bound when available; falls back to
    the conservative heuristic (0.5% of valuation) for non-triggered permits.
    Returns 0.0 when there's no useful signal.
    """
    if sp.art_budget_low is not None:
        return sp.art_budget_low
    if sp.permit.valuation:
        return sp.permit.valuation * 0.005
    return 0.0


@permits_bp.route("/permits-monitor")
def permits_monitor():
    return render_template("permits.html")


@permits_bp.route("/api/permits")
def api_permits():
    try:
        filters = ConnectorFilters(
            min_valuation=float(request.args.get("min_valuation", 5_000_000)),
            permit_type=request.args.get("permit_type", "all"),
            occupancy_type=request.args.get("occupancy_type", "all"),
            status_category=request.args.get("status_category", "pipeline"),
            date_from=request.args.get("date_from", ""),
            limit=min(int(request.args.get("limit", 50)), 200),
            source=request.args.get("source", "submitted"),
        )
        art_budget_min = float(request.args.get("art_budget_min", 0))
        require_ordinance = request.args.get("require_ordinance", "all")

        permits = la_connector.fetch(filters)

        # Post-filter: exact valuation threshold (server-side pre-filter is
        # approximate because the valuation field is stored as text)
        permits = [p for p in permits if p.valuation is None or p.valuation >= filters.min_valuation]

        # Score each permit for art commissioning relevance
        scored = score_permits(permits)

        # Only surface opportunities where the engine has a meaningful signal.
        # Low and None permits are not shown — this is an opportunity feed, not
        # a permit browser.
        opportunities = [
            sp for sp in scored
            if sp.relevance in (RelevanceLevel.HIGH, RelevanceLevel.MEDIUM)
        ]

        # Apply estimated art budget floor when requested.
        # Permits with no calculable budget are excluded when any minimum is set.
        if art_budget_min > 0:
            opportunities = [
                sp for sp in opportunities
                if _budget_sort_key(sp) >= art_budget_min
            ]

        # Ordinance filter:
        #   "yes" → ordinance triggered (PADFP-mandated art budget)
        #   "no"  → ordinance NOT triggered (pure project-characteristics scoring:
        #            keywords, occupancy type, scale — no PADFP involvement at all)
        if require_ordinance == "yes":
            opportunities = [sp for sp in opportunities if sp.ordinance_triggered]
        elif require_ordinance == "no":
            opportunities = [sp for sp in opportunities if not sp.ordinance_triggered]

        # Sort by estimated art budget descending (biggest opportunities first),
        # then by filing date descending (most recent within the same budget tier).
        opportunities.sort(
            key=lambda sp: (
                _budget_sort_key(sp),
                sp.permit.filing_date or date.min,
            ),
            reverse=True,
        )

        return jsonify({
            "permits": [sp.to_dict() for sp in opportunities],
            "count": len(opportunities),
            "source": filters.source,
            "status_category": filters.status_category,
        })

    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"error": f"Internal error: {exc}"}), 500


@permits_bp.route("/api/permits/metadata")
def api_permits_metadata():
    try:
        meta = la_connector.get_metadata()
        return jsonify({
            "city": meta.city,
            "state": meta.state,
            "datasets": meta.datasets,
            "data_freshness": meta.data_freshness,
            "known_limitations": meta.known_limitations,
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
