from typing import Any

from flask import Blueprint, jsonify, request

from auth import login_required
from access import tenant_guard
from . import service

bp = Blueprint("cost_centers", __name__, url_prefix="/api/cost-centers")
bp.before_request(tenant_guard)


@bp.route("", methods=["GET"])
@login_required
def list_cost_centers() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    active_only = request.args.get("active_only", "false").lower() == "true"
    try:
        return jsonify(service.list_cost_centers(business_id, active_only))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("", methods=["POST"])
@login_required
def create_cost_center() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_cost_center(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/<int:cost_center_id>", methods=["PUT"])
@login_required
def update_cost_center(cost_center_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_cost_center(cost_center_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/<int:cost_center_id>", methods=["DELETE"])
@login_required
def delete_cost_center(cost_center_id: int) -> Any:
    try:
        service.delete_cost_center(cost_center_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/summary", methods=["GET"])
@login_required
def cost_center_summary() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    try:
        return jsonify(service.cost_center_summary(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
