from __future__ import annotations

from typing import Any

from flask import Blueprint, Response, jsonify, request, session

from auth import admin_required
from access import grant_access, tenant_guard
from . import service

bp = Blueprint("backup", __name__, url_prefix="/api/backup")
bp.before_request(tenant_guard)


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


MAX_IMPORT_BYTES = 25 * 1024 * 1024


@bp.route("/import", methods=["POST"])
@admin_required
def import_data() -> Any:
    if request.content_length is not None and request.content_length > MAX_IMPORT_BYTES:
        return jsonify({"error": "Backup file is too large"}), 413
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        result = service.import_business(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    grant_access(session["user_id"], result["business_id"], "owner")
    return jsonify(result), 201
