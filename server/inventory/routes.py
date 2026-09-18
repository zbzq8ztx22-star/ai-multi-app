from typing import Any

from flask import Blueprint, jsonify, request

from auth import login_required
from access import tenant_guard
from . import service

bp = Blueprint("inventory", __name__, url_prefix="/api/inventory")
bp.before_request(tenant_guard)


@bp.route("/items", methods=["GET"])
@login_required
def items() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    active_only = request.args.get("active_only", "false").lower() == "true"
    try:
        return jsonify(service.list_items(business_id, active_only))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/items", methods=["POST"])
@login_required
def create_item() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_item(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/items/<int:item_id>", methods=["PUT"])
@login_required
def update_item(item_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_item(item_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/items/<int:item_id>", methods=["DELETE"])
@login_required
def delete_item(item_id: int) -> Any:
    try:
        service.delete_item(item_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/movements", methods=["GET"])
@login_required
def movements() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    item_id = request.args.get("item_id", type=int)
    try:
        return jsonify(service.list_movements(business_id, item_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/movements", methods=["POST"])
@login_required
def record_movement() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.record_movement(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/low-stock", methods=["GET"])
@login_required
def low_stock() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.low_stock_report(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/valuation", methods=["GET"])
@login_required
def valuation() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.inventory_valuation(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
