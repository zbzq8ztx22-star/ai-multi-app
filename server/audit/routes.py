from typing import Any

from flask import Blueprint, jsonify, request

from auth import admin_required
from csv_export import csv_response as _csv_response
from . import service

bp = Blueprint("audit", __name__, url_prefix="/api/audit")


@bp.route("/log", methods=["GET"])
@admin_required
def log() -> Any:
    module = request.args.get("module")
    limit = request.args.get("limit", 100, type=int)
    return jsonify(service.list_entries(module, limit))


@bp.route("/log/export", methods=["GET"])
@admin_required
def export_log() -> Any:
    module = request.args.get("module")
    limit = request.args.get("limit", 500, type=int)
    entries = service.list_entries(module, limit)
    rows = [["ID", "User ID", "Username", "Action", "Module", "Entity Type", "Entity ID", "Description", "Created At"]]
    for e in entries:
        rows.append([e.get("id", ""), e.get("user_id", ""), e.get("username", ""), e.get("action", ""), e.get("module", ""), e.get("entity_type", ""), e.get("entity_id", ""), e.get("description", ""), e.get("created_at", "")])
    return _csv_response(rows, "audit-log.csv")
