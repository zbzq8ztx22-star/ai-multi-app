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


@bp.route("/payments", methods=["GET"])
@login_required
def tax_payments() -> Any:
    business_id = request.args.get("business_id", type=int)
    tax_type = request.args.get("tax_type")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_tax_payments(business_id, tax_type))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/payments", methods=["POST"])
@admin_required
def create_tax_payment() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_tax_payment(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/payments/<int:payment_id>", methods=["DELETE"])
@admin_required
def delete_tax_payment(payment_id: int) -> Any:
    try:
        service.delete_tax_payment(payment_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/payments/summary", methods=["GET"])
@login_required
def tax_payment_summary() -> Any:
    business_id = request.args.get("business_id", type=int)
    year = request.args.get("year", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.tax_payment_summary(business_id, year))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
