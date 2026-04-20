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
from permits.connectors.cities.new_york import nyc_connector
from permits.connectors.cities.san_francisco import sf_connector
from permits.engine import score_permits, RelevanceLevel, _matches_public_sector_owner

permits_bp = Blueprint("permits", __name__)

# ── City connector registry ──────────────────────────────────────────────────

_CONNECTORS = {
    "los_angeles": la_connector,
    "new_york": nyc_connector,
    "san_francisco": sf_connector,
}

_SOURCE_LABELS = {
    "los_angeles": "LADBS via data.lacity.org",
    "new_york": "NYC DOB via data.cityofnewyork.us",
    "san_francisco": "SF DBI via data.sfgov.org",
}


def _get_connector(city_key: str):
    """Return the connector for a city key, or None if unknown."""
    return _CONNECTORS.get(city_key)


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


def _is_public_sector(sp) -> bool:
    """Check if a scored permit is a public-sector project."""
    patterns = sp.permit.raw_data.get("public_sector_owner_patterns", [])
    if patterns and _matches_public_sector_owner(sp.permit, patterns):
        return True
    return False


@permits_bp.route("/permits-monitor")
def permits_monitor():
    return render_template("permits.html")


_VALID_SECTORS = {"all", "public", "private"}


@permits_bp.route("/api/permits")
def api_permits():
    city_key = request.args.get("city", "los_angeles")
    connector = _get_connector(city_key)
    if connector is None:
        return jsonify({"error": f"Unknown city: {city_key}"}), 400

    try:
        min_valuation = float(request.args.get("min_valuation", 5_000_000))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid min_valuation: must be a number"}), 400
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid limit: must be an integer"}), 400
    try:
        art_budget_min = float(request.args.get("art_budget_min", 0))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid art_budget_min: must be a number"}), 400

    sector = request.args.get("sector", "all")
    if sector not in _VALID_SECTORS:
        return jsonify({"error": f"Invalid sector: must be all, public, or private"}), 400

    try:
        filters = ConnectorFilters(
            min_valuation=min_valuation,
            permit_type=request.args.get("permit_type", "all"),
            occupancy_type=request.args.get("occupancy_type", "all"),
            status_category=request.args.get("status_category", "pipeline"),
            date_from=request.args.get("date_from", ""),
            limit=limit,
            source=request.args.get("source", "submitted"),
        )

        # Back-compat: old include_ordinance param maps to sector logic
        include_ordinance_raw = request.args.get("include_ordinance")
        if include_ordinance_raw is not None and sector == "all":
            # Legacy callers: include_ordinance=true → all, false → private
            if include_ordinance_raw.lower() != "true":
                sector = "private"

        permits = connector.fetch(filters)

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

        # Sector filter:
        #   "all"     → everything High/Medium (default)
        #   "public"  → public-sector projects with ordinance-triggered art spending
        #   "private" → non-public-sector projects (ordinance-dependent excluded)
        if sector == "public":
            opportunities = [
                sp for sp in opportunities
                if sp.ordinance_triggered and _is_public_sector(sp)
            ]
        elif sector == "private":
            opportunities = [
                sp for sp in opportunities
                if not _is_public_sector(sp) and not sp.ordinance_dependent
            ]

        # Sort by estimated art budget descending (biggest opportunities first),
        # then by filing date descending (most recent within the same budget tier).
        opportunities.sort(
            key=lambda sp: (
                _budget_sort_key(sp),
                sp.permit.filing_date or date.min,
            ),
            reverse=True,
        )

        # Serialize. When viewing private sector, strip the ordinance trigger
        # line from reasons — it's noise in that view.
        permit_dicts = []
        for sp in opportunities:
            d = sp.to_dict()
            if sector == "private":
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
            "city": city_key,
            "source_label": _SOURCE_LABELS.get(city_key, ""),
        })

    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        return jsonify({"error": f"Internal error: {exc}"}), 500


@permits_bp.route("/api/permits/metadata")
def api_permits_metadata():
    city_key = request.args.get("city", "los_angeles")
    connector = _get_connector(city_key)
    if connector is None:
        return jsonify({"error": f"Unknown city: {city_key}"}), 400

    try:
        meta = connector.get_metadata()
        return jsonify({
            "city": meta.city,
            "state": meta.state,
            "datasets": meta.datasets,
            "data_freshness": meta.data_freshness,
            "known_limitations": meta.known_limitations,
            "source_label": _SOURCE_LABELS.get(city_key, ""),
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
