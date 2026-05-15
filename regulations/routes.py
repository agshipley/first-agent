from flask import Blueprint, jsonify, render_template, request, abort
from .db import get_db

regulations_bp = Blueprint("regulations", __name__)

_REG_TYPE_LABELS = {
    "S": "State law",
    "1": "Standard ordinance",
    "2": "Tiered-rate ordinance",
    "3": "Specific Plan / CPIO",
    "4": "Community Benefits Agreement",
    "5": "Density bonus program",
    "6": "Legacy redevelopment",
}


def _row_to_dict(row):
    d = dict(row)
    d["reg_type_label"] = _REG_TYPE_LABELS.get(d.get("reg_type") or "", "")
    return d


@regulations_bp.route("/regulations")
def regulations_index():
    return render_template("regulations.html", reg_type_labels=_REG_TYPE_LABELS)


@regulations_bp.route("/regulations/<int:reg_id>")
def regulation_detail(reg_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM regulations WHERE id = ?", (reg_id,)
    ).fetchone()
    conn.close()
    if row is None:
        abort(404)
    return render_template("regulations.html",
                           reg_type_labels=_REG_TYPE_LABELS,
                           open_id=reg_id)


@regulations_bp.route("/api/regulations")
def api_regulations():
    region = request.args.get("region", "").strip()
    mandatory = request.args.get("mandatory", "").strip()
    reg_type = request.args.get("reg_type", "").strip()
    q = request.args.get("q", "").strip()

    clauses = []
    params = []

    if region:
        clauses.append("region = ?")
        params.append(region)
    if mandatory:
        clauses.append("mandatory LIKE ?")
        params.append(f"%{mandatory}%")
    if reg_type:
        clauses.append("reg_type = ?")
        params.append(reg_type)
    if q:
        clauses.append(
            "(jurisdiction LIKE ? OR program_name LIKE ? OR notes LIKE ? OR threshold LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM regulations {where} ORDER BY id"

    conn = get_db()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return jsonify([_row_to_dict(r) for r in rows])


@regulations_bp.route("/api/regulations/<int:reg_id>")
def api_regulation_detail(reg_id):
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM regulations WHERE id = ?", (reg_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_row_to_dict(row))
