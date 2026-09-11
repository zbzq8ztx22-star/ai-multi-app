from typing import Any

from flask import Blueprint, Response, jsonify, request

from auth import admin_required
from . import service

bp = Blueprint("backup", __name__, url_prefix="/api/backup")


@bp.route("/export/<int:business_id>", methods=["GET"])
@admin_required
def export(business_id: int) -> Any:
    try:
        data = service.export_business(business_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    import json
    payload = json.dumps(data, indent=2, default=str)
    resp = Response(payload, mimetype="application/json")
    resp.headers["Content-Disposition"] = f'attachment; filename="backup-business-{business_id}.json"'
    return resp


@bp.route("/import", methods=["POST"])
@admin_required
def import_data() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.import_business(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
