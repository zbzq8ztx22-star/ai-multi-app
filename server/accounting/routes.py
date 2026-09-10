from typing import Any, Callable

from flask import Blueprint, jsonify, request, session

from audit import service as audit_service
from auth import admin_required, login_required
from . import service

bp = Blueprint("accounting", __name__, url_prefix="/api/accounting")


def _current_user() -> dict[str, Any] | None:
    if "user_id" not in session:
        return None
    return {"id": session.get("user_id"), "username": session.get("username", ""), "role": session.get("role", "")}


def _json_write(action: Callable[[dict[str, Any]], dict[str, Any]], module_name: str = "accounting", action_name: str = "create") -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        result = action(data)
        audit_service.log(action_name, module_name, _current_user(), entity_type=action.__qualname__.split(".")[0], entity_id=result.get("id"), description=str(result.get("description", result.get("invoice_number", result.get("reference", "")))))
        return jsonify(result), 201
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


@bp.route("/contacts", methods=["GET"])
@login_required
def contacts() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_contacts(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/contacts", methods=["POST"])
@admin_required
def create_contact() -> Any:
    return _json_write(service.create_contact)


@bp.route("/invoices", methods=["GET"])
@login_required
def invoices() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_invoices(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/invoices", methods=["POST"])
@admin_required
def create_invoice() -> Any:
    return _json_write(service.create_invoice)


@bp.route("/payments", methods=["POST"])
@admin_required
def create_payment() -> Any:
    return _json_write(service.record_payment)


@bp.route("/expenses", methods=["GET"])
@login_required
def expenses() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_expenses(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/expenses", methods=["POST"])
@admin_required
def create_expense() -> Any:
    return _json_write(service.create_expense)


@bp.route("/reports/profit-loss", methods=["GET"])
@login_required
def profit_loss() -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.profit_and_loss(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/balance-sheet", methods=["GET"])
@login_required
def financial_position() -> Any:
    business_id = request.args.get("business_id", type=int)
    as_of = request.args.get("as_of", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.balance_sheet(business_id, as_of))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/corporate-tax", methods=["GET"])
@login_required
def corporate_tax() -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.corporate_tax_summary(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/budgets", methods=["GET"])
@login_required
def budgets() -> Any:
    business_id = request.args.get("business_id", type=int)
    fiscal_year = request.args.get("fiscal_year", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_budgets(business_id, fiscal_year))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/budgets", methods=["POST"])
@admin_required
def create_budget() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        result = service.create_budget(data)
        audit_service.log("create", "accounting", _current_user(), entity_type="budget", entity_id=result.get("id"), description=f"Budget for account {data.get('account_id')}, year {data.get('fiscal_year')}")
        return jsonify(result), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/budgets/<int:budget_id>", methods=["PUT"])
@admin_required
def update_budget(budget_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        result = service.update_budget(budget_id, data)
        audit_service.log("update", "accounting", _current_user(), entity_type="budget", entity_id=budget_id, description=f"Updated budget to {data.get('budgeted_amount')}")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/budgets/<int:budget_id>", methods=["DELETE"])
@admin_required
def delete_budget(budget_id: int) -> Any:
    try:
        service.delete_budget(budget_id)
        audit_service.log("delete", "accounting", _current_user(), entity_type="budget", entity_id=budget_id, description="Deleted budget")
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/budget-vs-actual", methods=["GET"])
@login_required
def budget_vs_actual() -> Any:
    business_id = request.args.get("business_id", type=int)
    fiscal_year = request.args.get("fiscal_year", type=int)
    if business_id is None or fiscal_year is None:
        return jsonify({"error": "business_id and fiscal_year are required"}), 400
    try:
        return jsonify(service.budget_vs_actual(business_id, fiscal_year))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/ar-aging", methods=["GET"])
@login_required
def ar_aging() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    as_of = request.args.get("as_of")
    try:
        return jsonify(service.accounts_receivable_aging(business_id, as_of))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/ap-aging", methods=["GET"])
@login_required
def ap_aging() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    as_of = request.args.get("as_of")
    try:
        return jsonify(service.accounts_payable_aging(business_id, as_of))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/kpis", methods=["GET"])
@login_required
def kpis() -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.financial_kpis(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/cash-flow", methods=["GET"])
@login_required
def cash_flow() -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.cash_flow_statement(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/expense-breakdown", methods=["GET"])
@login_required
def expense_breakdown() -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.expense_breakdown(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/multi-year", methods=["GET"])
@login_required
def multi_year() -> Any:
    business_id = request.args.get("business_id", type=int)
    years_str = request.args.get("years", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        years = [int(y.strip()) for y in years_str.split(",") if y.strip()]
    except ValueError:
        return jsonify({"error": "years must be comma-separated integers"}), 400
    if not years or len(years) > 10:
        return jsonify({"error": "Provide 1-10 years"}), 400
    try:
        return jsonify(service.multi_year_comparison(business_id, years))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
