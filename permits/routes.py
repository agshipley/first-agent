"""
Flask routes for the Permits Intelligence tab.

Blueprint: permits_bp
Routes:
  GET /permits-monitor          → renders permits.html
  GET /api/permits              → returns ScoredPermit records as JSON
  GET /api/permits/metadata     → returns connector metadata
"""

from flask import Blueprint, request, jsonify, render_template

from permits.connectors.base import ConnectorFilters
from permits.connectors.cities.los_angeles import la_connector
from permits.engine import score_permits

permits_bp = Blueprint("permits", __name__)


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

        permits = la_connector.fetch(filters)

        # Post-filter: exact valuation threshold (server-side pre-filter is
        # approximate because the valuation field is stored as text)
        permits = [p for p in permits if p.valuation is None or p.valuation >= filters.min_valuation]

        # Score each permit for art commissioning relevance
        scored = score_permits(permits)

        return jsonify({
            "permits": [sp.to_dict() for sp in scored],
            "count": len(scored),
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
