from typing import Any, Callable

from flask import Blueprint, Response, jsonify, request, session

from audit import service as audit_service
from auth import admin_required, login_required
from . import service

bp = Blueprint("accounting", __name__, url_prefix="/api/accounting")


def _csv_response(rows: list[list[Any]], filename: str) -> Response:
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    for row in rows:
        writer.writerow(row)
    resp = Response(output.getvalue(), mimetype="text/csv")
    resp.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


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


@bp.route("/invoices/<int:invoice_id>", methods=["GET"])
@login_required
def invoice_detail(invoice_id: int) -> Any:
    invoice = service.get_invoice_detail(invoice_id)
    if invoice is None:
        return jsonify({"error": "Invoice not found"}), 404
    return jsonify(invoice)


@bp.route("/invoices/<int:invoice_id>/void", methods=["PUT"])
@admin_required
def void_invoice(invoice_id: int) -> Any:
    try:
        return jsonify(service.void_invoice(invoice_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/invoices/<int:invoice_id>/print", methods=["GET"])
@login_required
def print_invoice(invoice_id: int) -> Any:
    invoice = service.get_invoice_detail(invoice_id)
    if invoice is None:
        return jsonify({"error": "Invoice not found"}), 404
    balance = round(invoice["amount"] - invoice["amount_paid"], 2)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Invoice {invoice['invoice_number']}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 20px; color: #1a1a1a; }}
  .header {{ display: flex; justify-content: space-between; border-bottom: 2px solid #333; padding-bottom: 20px; }}
  .business-name {{ font-size: 24px; font-weight: bold; }}
  .invoice-title {{ font-size: 32px; color: #666; text-align: right; }}
  .details {{ margin: 30px 0; display: flex; justify-content: space-between; }}
  .label {{ color: #666; font-size: 12px; text-transform: uppercase; }}
  .value {{ font-size: 16px; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
  th {{ text-align: left; padding: 10px; border-bottom: 2px solid #333; color: #666; font-size: 12px; text-transform: uppercase; }}
  td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
  .totals {{ margin-left: auto; width: 300px; }}
  .totals-row {{ display: flex; justify-content: space-between; padding: 8px 0; }}
  .total {{ font-weight: bold; font-size: 18px; border-top: 2px solid #333; padding-top: 10px; }}
  .status {{ display: inline-block; padding: 4px 12px; border-radius: 4px; font-size: 12px; font-weight: bold; text-transform: uppercase; }}
  .status-open {{ background: #fef3c7; color: #92400e; }}
  .status-paid {{ background: #d1fae5; color: #065f46; }}
  .status-void {{ background: #fee2e2; color: #991b1b; }}
  @media print {{ .no-print {{ display: none; }} }}
</style></head><body>
  <div class="no-print" style="text-align:right;margin-bottom:20px"><button onclick="window.print()" style="padding:10px 20px;font-size:14px;cursor:pointer">Print / Save as PDF</button></div>
  <div class="header">
    <div><div class="business-name">{invoice['business_name']}</div>{f"<div>{invoice['business_dba']}</div>" if invoice.get('business_dba') else ""}</div>
    <div class="invoice-title">INVOICE</div>
  </div>
  <div class="details">
    <div><div class="label">Bill To</div><div class="value">{invoice['customer_name']}</div>{f"<div>{invoice['customer_email']}</div>" if invoice.get('customer_email') else ""}</div>
    <div style="text-align:right">
      <div class="label">Invoice Number</div><div class="value">{invoice['invoice_number']}</div>
      <div class="label" style="margin-top:10px">Issue Date</div><div class="value">{invoice['issue_date']}</div>
      <div class="label" style="margin-top:10px">Due Date</div><div class="value">{invoice['due_date']}</div>
      <div class="label" style="margin-top:10px">Status</div><div class="value"><span class="status status-{invoice['status']}">{invoice['status']}</span></div>
    </div>
  </div>
  <table><thead><tr><th>Description</th><th style="text-align:right">Amount</th></tr></thead>
  <tbody><tr><td>{invoice['description']}</td><td style="text-align:right">${invoice['amount']:,.2f}</td></tr></tbody></table>
  <div class="totals">
    <div class="totals-row"><span>Subtotal</span><span>${invoice['amount']:,.2f}</span></div>
    <div class="totals-row"><span>Paid</span><span>${invoice['amount_paid']:,.2f}</span></div>
    <div class="totals-row total"><span>Balance Due</span><span>${balance:,.2f}</span></div>
  </div>
</body></html>"""
    return Response(html, mimetype="text/html")


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


@bp.route("/expenses/pending", methods=["GET"])
@login_required
def pending_expenses() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_pending_expenses(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/expenses/<int:expense_id>/approve", methods=["PUT"])
@admin_required
def approve_expense(expense_id: int) -> Any:
    data = request.get_json(silent=True) or {}
    approver = data.get("approver", "")
    try:
        return jsonify(service.approve_expense(expense_id, approver))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/expenses/<int:expense_id>/reject", methods=["PUT"])
@admin_required
def reject_expense(expense_id: int) -> Any:
    data = request.get_json(silent=True) or {}
    approver = data.get("approver", "")
    try:
        return jsonify(service.reject_expense(expense_id, approver))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


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


@bp.route("/reconciliations", methods=["GET"])
@login_required
def reconciliations() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_reconciliations(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reconciliations", methods=["POST"])
@admin_required
def create_reconciliation() -> Any:
    return _json_write(service.create_reconciliation)


@bp.route("/reconciliations/<int:reconciliation_id>", methods=["PUT"])
@admin_required
def update_reconciliation(reconciliation_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_reconciliation(reconciliation_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reconciliations/<int:reconciliation_id>", methods=["DELETE"])
@admin_required
def delete_reconciliation(reconciliation_id: int) -> Any:
    try:
        service.delete_reconciliation(reconciliation_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/export/profit-loss.csv", methods=["GET"])
@login_required
def export_profit_loss() -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        pl = service.profit_and_loss(business_id, start_date, end_date)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    rows = [["Profit & Loss", f"{pl['start_date']} to {pl['end_date']}"]]
    rows.append([])
    rows.append(["Section", "Account Code", "Account Name", "Amount"])
    for r in pl["revenue"]:
        rows.append(["Revenue", r["code"], r["name"], r["amount"]])
    rows.append(["", "", "Total Revenue", pl["total_revenue"]])
    for r in pl["expenses"]:
        rows.append(["Expense", r["code"], r["name"], r["amount"]])
    rows.append(["", "", "Total Expenses", pl["total_expenses"]])
    rows.append(["", "", "Net Income", pl["net_income"]])
    return _csv_response(rows, "profit-loss.csv")


@bp.route("/export/balance-sheet.csv", methods=["GET"])
@login_required
def export_balance_sheet() -> Any:
    business_id = request.args.get("business_id", type=int)
    as_of = request.args.get("as_of", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        bs = service.balance_sheet(business_id, as_of)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    rows = [["Balance Sheet", f"As of {bs['as_of']}"]]
    rows.append([])
    rows.append(["Section", "Account Code", "Account Name", "Amount"])
    for r in bs["assets"]:
        rows.append(["Asset", r["code"], r["name"], r["amount"]])
    rows.append(["", "", "Total Assets", bs["total_assets"]])
    for r in bs["liabilities"]:
        rows.append(["Liability", r["code"], r["name"], r["amount"]])
    rows.append(["", "", "Total Liabilities", bs["total_liabilities"]])
    for r in bs["equity"]:
        rows.append(["Equity", r["code"], r["name"], r["amount"]])
    rows.append(["", "", "Current Earnings", bs["current_earnings"]])
    rows.append(["", "", "Total Equity", bs["total_equity"]])
    rows.append(["", "", "Balanced", "Yes" if bs["balanced"] else "No"])
    return _csv_response(rows, "balance-sheet.csv")


@bp.route("/export/trial-balance.csv", methods=["GET"])
@login_required
def export_trial_balance() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        tb = service.trial_balance(business_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    rows = [["Account Code", "Account Name", "Type", "Debits", "Credits"]]
    for a in tb["accounts"]:
        rows.append([a["code"], a["name"], a["account_type"], a["debits"], a["credits"]])
    rows.append(["", "", "Totals", tb["total_debits"], tb["total_credits"]])
    rows.append(["", "", "Balanced", "", "Yes" if tb["balanced"] else "No"])
    return _csv_response(rows, "trial-balance.csv")


@bp.route("/export/general-ledger.csv", methods=["GET"])
@login_required
def export_general_ledger() -> Any:
    business_id = request.args.get("business_id", type=int)
    account_id = request.args.get("account_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        ledger = service.general_ledger(business_id, account_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    rows = [["Date", "Reference", "Description", "Account Code", "Account Name", "Line Description", "Debit", "Credit"]]
    for line in ledger:
        rows.append([line["entry_date"], line["reference"], line["entry_description"], line["account_code"], line["account_name"], line["description"], line["debit"], line["credit"]])
    return _csv_response(rows, "general-ledger.csv")


@bp.route("/recurring-expenses", methods=["GET"])
@login_required
def recurring_expenses() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_recurring_expenses(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/recurring-expenses", methods=["POST"])
@admin_required
def create_recurring_expense() -> Any:
    return _json_write(service.create_recurring_expense)


@bp.route("/recurring-expenses/<int:recurring_id>", methods=["PUT"])
@admin_required
def update_recurring_expense(recurring_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_recurring_expense(recurring_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/recurring-expenses/<int:recurring_id>", methods=["DELETE"])
@admin_required
def delete_recurring_expense(recurring_id: int) -> Any:
    try:
        service.delete_recurring_expense(recurring_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/recurring-expenses/post-due", methods=["POST"])
@admin_required
def post_due_recurring() -> Any:
    business_id = request.args.get("business_id", type=int)
    as_of = request.args.get("as_of")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        posted = service.post_due_recurring_expenses(business_id, as_of)
        return jsonify({"posted_count": len(posted), "posted": posted})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/closing-periods", methods=["GET"])
@login_required
def closing_periods() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_closing_periods(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/closing-periods", methods=["POST"])
@admin_required
def close_period() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.close_period(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/closing-periods/<int:period_id>", methods=["DELETE"])
@admin_required
def reopen_period(period_id: int) -> Any:
    try:
        service.reopen_period(period_id)
        return jsonify({"reopened": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/closing-periods/check", methods=["GET"])
@login_required
def check_period_closed() -> Any:
    business_id = request.args.get("business_id", type=int)
    entry_date = request.args.get("entry_date", "")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.is_period_closed(business_id, entry_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/statements/customer/<int:customer_id>", methods=["GET"])
@login_required
def customer_statement(customer_id: int) -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.customer_statement(business_id, customer_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/statements/vendor/<int:vendor_id>", methods=["GET"])
@login_required
def vendor_statement(vendor_id: int) -> Any:
    business_id = request.args.get("business_id", type=int)
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.vendor_statement(business_id, vendor_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/account-groups", methods=["GET"])
@login_required
def account_groups() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_account_groups(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/account-groups", methods=["POST"])
@admin_required
def create_account_group() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_account_group(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/account-groups/<int:group_id>", methods=["PUT"])
@admin_required
def update_account_group(group_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_account_group(group_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/account-groups/<int:group_id>", methods=["DELETE"])
@admin_required
def delete_account_group(group_id: int) -> Any:
    try:
        service.delete_account_group(group_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/accounts/<int:account_id>/assign-group", methods=["PUT"])
@admin_required
def assign_account_to_group(account_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    group_id = data.get("group_id")
    if group_id is None:
        return jsonify({"error": "group_id is required"}), 400
    try:
        return jsonify(service.assign_account_to_group(account_id, int(group_id)))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/payment-terms", methods=["GET"])
@login_required
def payment_terms() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_payment_terms(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/payment-terms", methods=["POST"])
@admin_required
def create_payment_terms() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_payment_terms(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/payment-terms/<int:term_id>", methods=["PUT"])
@admin_required
def update_payment_terms(term_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_payment_terms(term_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/payment-terms/<int:term_id>", methods=["DELETE"])
@admin_required
def delete_payment_terms(term_id: int) -> Any:
    try:
        service.delete_payment_terms(term_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/credit-notes", methods=["GET"])
@login_required
def credit_notes() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_credit_notes(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/credit-notes", methods=["POST"])
@admin_required
def create_credit_note() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_credit_note(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/credit-notes/<int:credit_id>/void", methods=["PUT"])
@admin_required
def void_credit_note(credit_id: int) -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.void_credit_note(business_id, credit_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/depreciation-assets", methods=["GET"])
@login_required
def depreciation_assets() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_depreciation_assets(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/depreciation-assets", methods=["POST"])
@admin_required
def create_depreciation_asset() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_depreciation_asset(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/depreciation-assets/<int:asset_id>/schedule", methods=["GET"])
@login_required
def depreciation_schedule(asset_id: int) -> Any:
    try:
        return jsonify(service.depreciation_schedule(asset_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/depreciation-assets/<int:asset_id>/post", methods=["POST"])
@admin_required
def post_depreciation(asset_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    through_date = data.get("through_date")
    if not through_date:
        return jsonify({"error": "through_date is required"}), 400
    try:
        return jsonify(service.post_depreciation(asset_id, through_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/budgets/alerts", methods=["GET"])
@login_required
def budget_alerts() -> Any:
    business_id = request.args.get("business_id", type=int)
    fiscal_year = request.args.get("fiscal_year", type=int)
    threshold = request.args.get("threshold_percent", default=80.0, type=float)
    if business_id is None or fiscal_year is None:
        return jsonify({"error": "business_id and fiscal_year are required"}), 400
    try:
        return jsonify(service.budget_variance_alerts(business_id, fiscal_year, threshold))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/financial-ratios", methods=["GET"])
@login_required
def financial_ratios() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    as_of_date = request.args.get("as_of_date")
    try:
        return jsonify(service.financial_ratios(business_id, as_of_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/projects", methods=["GET"])
@login_required
def projects() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    status = request.args.get("status")
    try:
        return jsonify(service.list_projects(business_id, status))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/projects", methods=["POST"])
@admin_required
def create_project() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_project(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/projects/<int:project_id>", methods=["PUT"])
@admin_required
def update_project(project_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_project(project_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/projects/<int:project_id>", methods=["DELETE"])
@admin_required
def delete_project(project_id: int) -> Any:
    try:
        service.delete_project(project_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/projects/<int:project_id>/profitability", methods=["GET"])
@login_required
def project_profitability(project_id: int) -> Any:
    try:
        return jsonify(service.project_profitability(project_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/aging-summary", methods=["GET"])
@login_required
def aging_summary() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    as_of = request.args.get("as_of")
    try:
        return jsonify(service.aging_summary(business_id, as_of))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/bank-transactions", methods=["GET"])
@login_required
def bank_transactions() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    account_id = request.args.get("account_id", type=int)
    cleared = request.args.get("cleared")
    cleared_flag = None
    if cleared is not None:
        cleared_flag = cleared.lower() == "true"
    try:
        return jsonify(service.list_bank_transactions(business_id, account_id, cleared_flag))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/bank-transactions", methods=["POST"])
@admin_required
def create_bank_transaction() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_bank_transaction(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/bank-transactions/<int:tx_id>/match", methods=["PUT"])
@admin_required
def match_bank_transaction(tx_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "journal_line_id" not in data:
        return jsonify({"error": "journal_line_id is required"}), 400
    try:
        return jsonify(service.match_bank_transaction(tx_id, int(data["journal_line_id"])))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/bank-transactions/<int:tx_id>/unmatch", methods=["PUT"])
@admin_required
def unmatch_bank_transaction(tx_id: int) -> Any:
    try:
        return jsonify(service.unmatch_bank_transaction(tx_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/bank-transactions/<int:tx_id>", methods=["DELETE"])
@admin_required
def delete_bank_transaction(tx_id: int) -> Any:
    try:
        service.delete_bank_transaction(tx_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/bank-reconciliation/summary", methods=["GET"])
@login_required
def bank_reconciliation_summary() -> Any:
    business_id = request.args.get("business_id", type=int)
    account_id = request.args.get("account_id", type=int)
    if business_id is None or account_id is None:
        return jsonify({"error": "business_id and account_id are required"}), 400
    try:
        return jsonify(service.bank_reconciliation_summary(business_id, account_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/sales-tax-rates", methods=["GET"])
@login_required
def sales_tax_rates() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_sales_tax_rates(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/sales-tax-rates", methods=["POST"])
@admin_required
def create_sales_tax_rate() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_sales_tax_rate(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/sales-tax-rates/<int:rate_id>", methods=["PUT"])
@admin_required
def update_sales_tax_rate(rate_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.update_sales_tax_rate(rate_id, data))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/sales-tax-rates/<int:rate_id>", methods=["DELETE"])
@admin_required
def delete_sales_tax_rate(rate_id: int) -> Any:
    try:
        service.delete_sales_tax_rate(rate_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/sales-tax/calculate", methods=["GET"])
@login_required
def calculate_sales_tax() -> Any:
    amount = request.args.get("amount", type=float)
    rate = request.args.get("rate", type=float)
    if amount is None or rate is None:
        return jsonify({"error": "amount and rate are required"}), 400
    try:
        return jsonify(service.calculate_sales_tax(amount, rate))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/sales-tax/summary", methods=["GET"])
@login_required
def sales_tax_summary() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    try:
        return jsonify(service.sales_tax_summary(business_id, start_date, end_date))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/purchase-orders", methods=["GET"])
@login_required
def purchase_orders() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    status = request.args.get("status")
    try:
        return jsonify(service.list_purchase_orders(business_id, status))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/purchase-orders", methods=["POST"])
@admin_required
def create_purchase_order() -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        return jsonify(service.create_purchase_order(data)), 201
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/purchase-orders/<int:po_id>/status", methods=["PUT"])
@admin_required
def update_purchase_order_status(po_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or "status" not in data:
        return jsonify({"error": "status is required"}), 400
    try:
        return jsonify(service.update_purchase_order_status(po_id, data["status"]))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/purchase-orders/<int:po_id>", methods=["DELETE"])
@admin_required
def delete_purchase_order(po_id: int) -> Any:
    try:
        service.delete_purchase_order(po_id)
        return jsonify({"deleted": True})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/fixed-asset-register", methods=["GET"])
@login_required
def fixed_asset_register() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.fixed_asset_register(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/depreciation-assets/<int:asset_id>/dispose", methods=["POST"])
@admin_required
def dispose_fixed_asset(asset_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    disposal_date = data.get("disposal_date")
    disposal_price = data.get("disposal_price")
    gain_loss_account_id = data.get("gain_loss_account_id")
    if not disposal_date or disposal_price is None or gain_loss_account_id is None:
        return jsonify({"error": "disposal_date, disposal_price, and gain_loss_account_id are required"}), 400
    try:
        return jsonify(service.dispose_fixed_asset(asset_id, disposal_date, disposal_price, gain_loss_account_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/cash-flow-forecast", methods=["GET"])
@login_required
def cash_flow_forecast() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    months = request.args.get("months", 3, type=int)
    try:
        return jsonify(service.cash_flow_forecast(business_id, months))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/reports/1099", methods=["GET"])
@login_required
def report_1099() -> Any:
    business_id = request.args.get("business_id", type=int)
    tax_year = request.args.get("tax_year", type=int)
    if business_id is None or tax_year is None:
        return jsonify({"error": "business_id and tax_year are required"}), 400
    try:
        return jsonify(service.report_1099(business_id, tax_year))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/contacts/<int:contact_id>/1099", methods=["PUT"])
@admin_required
def update_contact_1099(contact_id: int) -> Any:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Request body must be JSON"}), 400
    is_1099 = data.get("is_1099", False)
    tax_id = data.get("tax_id", "")
    try:
        return jsonify(service.update_contact_1099(contact_id, is_1099, tax_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@bp.route("/contacts/1099-vendors", methods=["GET"])
@login_required
def list_1099_vendors() -> Any:
    business_id = request.args.get("business_id", type=int)
    if business_id is None:
        return jsonify({"error": "business_id is required"}), 400
    try:
        return jsonify(service.list_1099_vendors(business_id))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
