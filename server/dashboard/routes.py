from typing import Any

from flask import Blueprint, jsonify

from auth import login_required
from . import service

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.route("/overview", methods=["GET"])
@login_required
def overview() -> Any:
    return jsonify(service.overview())
