from typing import Any

from flask import Blueprint, jsonify, request

from auth import login_required
from access import tenant_guard
from . import service

bp = Blueprint("currency", __name__, url_prefix="/api/currency")
bp.before_request(tenant_guard)


@bp.route("/currencies", methods=["GET"])
@login_required
def currencies() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_currencies(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/currencies", methods=["POST"])
@login_required
def create_currency() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_currency(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/rates", methods=["GET"])
@login_required
def rates() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_exchange_rates(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/rates", methods=["POST"])
@login_required
def set_rate() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.set_exchange_rate(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/convert", methods=["GET"])
@login_required
def convert() -> Any:
    business_id = request.args.get("business_id", type=int)
    amount = request.args.get("amount", type=float)
    from_id = request.args.get("from_currency_id", type=int)
    to_id = request.args.get("to_currency_id", type=int)
    rate_date = request.args.get("rate_date")
    if business_id is None or amount is None or from_id is None or to_id is None:
        return jsonify({"error": "business_id, amount, from_currency_id, and to_currency_id are required"}), 400
    try:
        return jsonify(service.convert_amount(business_id, amount, from_id, to_id, rate_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
