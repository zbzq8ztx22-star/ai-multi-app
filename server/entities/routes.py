from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

from auth import admin_required, login_required
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
    return jsonify(service.list_businesses())


@bp.route("/businesses", methods=["POST"])
@admin_required
def create_business() -> Any:
    data = _body()
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_business(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
