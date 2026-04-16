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
        include_ordinance = request.args.get("include_ordinance", "false").lower() == "true"

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

        # Ordinance toggle (default OFF):
        #   OFF → exclude permits where ordinance is load-bearing for H/M status.
        #         Shows only what the engine finds on pure project characteristics.
        #   ON  → include everything (including PADFP-dependent permits).
        if not include_ordinance:
            opportunities = [sp for sp in opportunities if not sp.ordinance_dependent]

        # Sort by estimated art budget descending (biggest opportunities first),
        # then by filing date descending (most recent within the same budget tier).
        opportunities.sort(
            key=lambda sp: (
                _budget_sort_key(sp),
                sp.permit.filing_date or date.min,
            ),
            reverse=True,
        )

        # Serialize. When PADFP is toggled OFF, strip the ordinance trigger line
        # from reasons — it's noise in a view the user explicitly filtered away.
        permit_dicts = []
        for sp in opportunities:
            d = sp.to_dict()
            if not include_ordinance:
                d["relevance_reasons"] = [
                    r for r in d["relevance_reasons"]
                    if not r.startswith("Triggers ")
                ]
            permit_dicts.append(d)

        # Determine data freshness: use most recent filing date from results
        freshness_text = ""
        if permit_dicts:
            recent_dates = [
                sp.permit.filing_date for sp in opportunities
                if sp.permit.filing_date
            ]
            if recent_dates:
                most_recent = max(recent_dates)
                freshness_text = most_recent.strftime("%B %d, %Y")

        return jsonify({
            "permits": permit_dicts,
            "count": len(opportunities),
            "source": filters.source,
            "status_category": filters.status_category,
            "data_freshness": freshness_text,
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
