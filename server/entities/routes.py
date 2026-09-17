from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request, session

from auth import admin_required, login_required
from access import BUSINESS_ROLES, grant_access, list_grants, require_business_access, revoke_access
from . import service

bp = Blueprint("entities", __name__, url_prefix="/api/entities")


def _body() -> dict[str, Any] | None:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


@bp.route("/taxpayers", methods=["GET"])
@login_required
def taxpayers() -> Any:
    return jsonify(service.list_taxpayers())


@bp.route("/taxpayers", methods=["POST"])
@admin_required
def create_taxpayer() -> Any:
    data = _body()
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_taxpayer(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/businesses", methods=["GET"])
@login_required
def businesses() -> Any:
    return jsonify(service.list_businesses(session["user_id"]))


@bp.route("/businesses", methods=["POST"])
@login_required
def create_business() -> Any:
    data = _body()
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        business = service.create_business(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    grant_access(session["user_id"], business["id"], "owner")
    return jsonify(business), 201


@bp.route("/businesses/<int:business_id>/access", methods=["GET"])
@login_required
def business_access_list(business_id: int) -> Any:
    denied = require_business_access(business_id, "owner")
    if denied is not None:
        return denied
    return jsonify(list_grants(business_id))


@bp.route("/businesses/<int:business_id>/access", methods=["POST"])
@login_required
def business_access_grant(business_id: int) -> Any:
    denied = require_business_access(business_id, "owner")
    if denied is not None:
        return denied
    data = _body()
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    user_id = data.get("user_id")
    role = str(data.get("role", ""))
    if not isinstance(user_id, int):
        return jsonify({"error": "user_id is required"}), 400
    if role not in BUSINESS_ROLES:
        return jsonify({"error": "Invalid role"}), 400
    try:
        grant_access(user_id, business_id, role)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"user_id": user_id, "business_id": business_id, "role": role}), 201


@bp.route("/businesses/<int:business_id>/access/<int:user_id>", methods=["DELETE"])
@login_required
def business_access_revoke(business_id: int, user_id: int) -> Any:
    denied = require_business_access(business_id, "owner")
    if denied is not None:
        return denied
    try:
        revoke_access(user_id, business_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"revoked": True})
