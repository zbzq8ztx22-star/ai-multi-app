from typing import Any

from flask import Blueprint, jsonify, request

from auth import admin_required, login_required
from . import service

bp = Blueprint("tax", __name__, url_prefix="/api/tax")


@bp.route("/returns", methods=["GET"])
@login_required
def returns() -> Any:
    taxpayer_id = request.args.get("taxpayer_id", type=int)
    return jsonify(service.list_returns(taxpayer_id))


@bp.route("/returns", methods=["POST"])
@admin_required
def create_return() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.save_return(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/returns/<int:return_id>", methods=["PUT"])
@admin_required
def update_return(return_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.save_return(data, return_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
