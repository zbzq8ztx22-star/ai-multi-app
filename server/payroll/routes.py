from __future__ import annotations

import csv
import io
from typing import Any

from flask import Blueprint, Response, jsonify, request

from . import assistant, service

bp = Blueprint("payroll", __name__, url_prefix="/api/payroll")


@bp.before_request
def _require_login() -> Any:
    """All payroll endpoints require an authenticated session."""
    from auth import login_required

    return login_required(lambda: None)()


def _get_json_body() -> dict[str, Any] | None:
    if not request.is_json:
        return None
    return request.get_json(silent=True)


def _json_error(message: str, status: int = 400):
    return jsonify({"error": message}), status


# --------------------------------------------------------------------------- #
# Employees
# --------------------------------------------------------------------------- #

@bp.route("/employees", methods=["GET", "POST"])
def employees():
    if request.method == "GET":
        return jsonify(service.list_employees())

    body = _get_json_body()
    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object")
    try:
        return jsonify(service.create_employee(body)), 201
    except ValueError as exc:
        return _json_error(str(exc))


@bp.route("/employees/<int:employee_id>", methods=["GET", "PUT", "DELETE"])
def employee(employee_id: int):
    if request.method == "GET":
        record = service.get_employee(employee_id)
        if record is None:
            return _json_error("Employee not found", 404)
        return jsonify(record)

    if request.method == "DELETE":
        if service.delete_employee(employee_id):
            return jsonify({"deleted": True})
        return _json_error("Employee not found", 404)

    body = _get_json_body()
    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object")
    try:
        return jsonify(service.update_employee(employee_id, body))
    except ValueError as exc:
        return _json_error(str(exc))


# --------------------------------------------------------------------------- #
# Pay periods
# --------------------------------------------------------------------------- #

@bp.route("/pay-periods", methods=["GET", "POST"])
def pay_periods():
    if request.method == "GET":
        return jsonify(service.list_pay_periods())

    body = _get_json_body()
    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object")
    try:
        return jsonify(service.create_pay_period(body)), 201
    except ValueError as exc:
        return _json_error(str(exc))


@bp.route("/pay-periods/<int:period_id>", methods=["GET", "PUT", "DELETE"])
def pay_period(period_id: int):
    if request.method == "GET":
        record = service.get_pay_period(period_id)
        if record is None:
            return _json_error("Pay period not found", 404)
        return jsonify(record)

    if request.method == "DELETE":
        if service.delete_pay_period(period_id):
            return jsonify({"deleted": True})
        return _json_error("Pay period not found", 404)

    body = _get_json_body()
    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object")
    try:
        return jsonify(service.update_pay_period(period_id, body))
    except ValueError as exc:
        return _json_error(str(exc))


# --------------------------------------------------------------------------- #
# Payslips
# --------------------------------------------------------------------------- #

@bp.route("/payslips", methods=["GET", "POST"])
def payslips():
    if request.method == "GET":
        employee_id = request.args.get("employee_id", type=int)
        period_id = request.args.get("period_id", type=int)
        return jsonify(service.list_payslips(employee_id=employee_id, period_id=period_id))

    body = _get_json_body()
    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object")
    employee_id = body.get("employee_id")
    period_id = body.get("period_id")
    if not isinstance(employee_id, int) or not isinstance(period_id, int):
        return _json_error("employee_id and period_id must be integers")
    try:
        return jsonify(service.create_payslip(employee_id, period_id, body)), 201
    except ValueError as exc:
        return _json_error(str(exc))


@bp.route("/payslips/<int:payslip_id>", methods=["GET", "PUT", "DELETE"])
def payslip(payslip_id: int):
    if request.method == "GET":
        record = service.get_payslip(payslip_id)
        if record is None:
            return _json_error("Payslip not found", 404)
        return jsonify(record)

    if request.method == "DELETE":
        if service.delete_payslip(payslip_id):
            return jsonify({"deleted": True})
        return _json_error("Payslip not found", 404)

    body = _get_json_body()
    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object")
    try:
        return jsonify(service.update_payslip(payslip_id, body))
    except ValueError as exc:
        return _json_error(str(exc))


@bp.route("/assistant", methods=["POST"])
def payroll_assistant():
    body = _get_json_body()
    if not isinstance(body, dict):
        return _json_error("Request body must be a JSON object")

    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return _json_error("message is required and must be a non-empty string")

    session_id = body.get("session_id")
    if session_id is not None and (not isinstance(session_id, str) or not session_id):
        return _json_error("session_id must be a non-empty string")

    committee_review = body.get("committee_review", False)
    if not isinstance(committee_review, bool):
        return _json_error("committee_review must be a boolean")

    result = assistant.ask(message.strip(), session_id, committee_review)
    if "error" in result:
        return _json_error(result["error"], 502)
    return jsonify(result)


@bp.route("/reports/<int:period_id>", methods=["GET"])
def payroll_report(period_id: int):
    try:
        report = service.get_payroll_report(period_id)
        return jsonify(report)
    except ValueError as exc:
        return _json_error(str(exc), 404)


@bp.route("/reports/<int:period_id>/csv", methods=["GET"])
def payroll_report_csv(period_id: int):
    try:
        report = service.get_payroll_report(period_id)
    except ValueError as exc:
        return _json_error(str(exc), 404)

    fieldnames = [
        "employee_id",
        "employee_name",
        "position",
        "pay_type",
        "period_start",
        "period_end",
        "regular_hours",
        "overtime_hours",
        "gross_pay",
        "federal_tax",
        "state_tax",
        "fica_tax",
        "medicare_tax",
        "other_deductions",
        "net_pay",
    ]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(report["rows"])
    csv_data = output.getvalue()

    filename = f"payroll_{report['period']['start_date']}_{report['period']['end_date']}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
