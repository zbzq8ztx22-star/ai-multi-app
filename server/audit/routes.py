from typing import Any

from flask import Blueprint, jsonify, request

from auth import admin_required
from . import service

bp = Blueprint("audit", __name__, url_prefix="/api/audit")


@bp.route("/log", methods=["GET"])
@admin_required
def log() -> Any:
    module = request.args.get("module")
    limit = request.args.get("limit", 100, type=int)
    return jsonify(service.list_entries(module, limit))
