from typing import Any

from flask import Blueprint, jsonify, request

from auth import login_required
from . import service
from . import calendar_service

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.route("/overview", methods=["GET"])
@login_required
def overview() -> Any:
    return jsonify(service.overview())


@bp.route("/calendar", methods=["GET"])
@login_required
def calendar() -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(calendar_service.financial_calendar(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
