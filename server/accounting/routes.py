from typing import Any, Callable

from flask import Blueprint, jsonify, request

from auth import admin_required, login_required
from . import service

bp = Blueprint("accounting", __name__, url_prefix="/api/accounting")


def _json_write(action: Callable[[dict[str, Any]], dict[str, Any]]) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(action(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/accounts", methods=["GET"])
@login_required
def accounts() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_accounts(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/accounts", methods=["POST"])
@admin_required
def create_account() -> Any:
    return _json_write(service.create_account)


@bp.route("/entries", methods=["GET"])
@login_required
def entries() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_entries(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/entries", methods=["POST"])
@admin_required
def create_entry() -> Any:
    return _json_write(service.create_entry)


@bp.route("/trial-balance", methods=["GET"])
@login_required
def trial_balance() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.trial_balance(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/ledger", methods=["GET"])
@login_required
def ledger() -> Any:
    business_id = request.args.get("business_id", type=int)
    account_id = request.args.get("account_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.general_ledger(business_id, account_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
