from __future__ import annotations

import datetime
import sqlite3
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _add_months, _date, _iter_occurrences, _money, _require_business


def _account_balances(conn: sqlite3.Connection, business_id: int, end_date: str, start_date: str | None = None) -> list[dict[str, Any]]:
    conditions = ["accounts.business_id = ?", "journal_entries.status = 'posted'", "journal_entries.entry_date <= ?"]
    params: list[Any] = [business_id, end_date]
    if start_date:
        conditions.append("journal_entries.entry_date >= ?")
        params.append(start_date)
    rows = conn.execute(
        f"""SELECT accounts.id, accounts.code, accounts.name, accounts.account_type,
        ROUND(COALESCE(SUM(journal_lines.debit), 0), 2) AS debits,
        ROUND(COALESCE(SUM(journal_lines.credit), 0), 2) AS credits
        FROM accounts LEFT JOIN journal_lines ON journal_lines.account_id = accounts.id
        LEFT JOIN journal_entries ON journal_entries.id = journal_lines.entry_id
        WHERE {' AND '.join(conditions)} GROUP BY accounts.id ORDER BY accounts.code""",
        params,
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def profit_and_loss(business_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    start_date = _date(start_date, "start_date")
    end_date = _date(end_date, "end_date")
    if end_date < start_date:
        raise ValueError("end_date cannot be before start_date")
    with get_db() as conn:
        _require_business(conn, business_id)
        balances = _account_balances(conn, business_id, end_date, start_date)
    revenue = [{**row, "amount": round(row["credits"] - row["debits"], 2)} for row in balances if row["account_type"] == "revenue"]
    expenses = [{**row, "amount": round(row["debits"] - row["credits"], 2)} for row in balances if row["account_type"] == "expense"]
    total_revenue = round(sum(row["amount"] for row in revenue), 2)
    total_expenses = round(sum(row["amount"] for row in expenses), 2)
    return {"start_date": start_date, "end_date": end_date, "revenue": revenue, "expenses": expenses, "total_revenue": total_revenue, "total_expenses": total_expenses, "net_income": round(total_revenue - total_expenses, 2)}


def balance_sheet(business_id: int, as_of: str) -> dict[str, Any]:
    as_of = _date(as_of, "as_of")
    with get_db() as conn:
        _require_business(conn, business_id)
        balances = _account_balances(conn, business_id, as_of)
    assets = [{**row, "amount": round(row["debits"] - row["credits"], 2)} for row in balances if row["account_type"] == "asset"]
    liabilities = [{**row, "amount": round(row["credits"] - row["debits"], 2)} for row in balances if row["account_type"] == "liability"]
    equity = [{**row, "amount": round(row["credits"] - row["debits"], 2)} for row in balances if row["account_type"] == "equity"]
    revenue = sum(row["credits"] - row["debits"] for row in balances if row["account_type"] == "revenue")
    expenses = sum(row["debits"] - row["credits"] for row in balances if row["account_type"] == "expense")
    current_earnings = round(revenue - expenses, 2)
    total_assets = round(sum(row["amount"] for row in assets), 2)
    total_liabilities = round(sum(row["amount"] for row in liabilities), 2)
    total_equity = round(sum(row["amount"] for row in equity) + current_earnings, 2)
    return {"as_of": as_of, "assets": assets, "liabilities": liabilities, "equity": equity, "current_earnings": current_earnings, "total_assets": total_assets, "total_liabilities": total_liabilities, "total_equity": total_equity, "balanced": round(total_assets - total_liabilities - total_equity, 2) == 0}


CORPORATE_FEDERAL_RATE = 0.21


def corporate_tax_summary(business_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    """Derive a corporate tax estimate from posted accounting results.

    Consumes the Profit & Loss read model so corporate tax always reflects the
    same posted entries used by financial reports. The estimate is a flat
    federal rate applied to taxable net income; it is an estimate only.
    """
    pl = profit_and_loss(business_id, start_date, end_date)
    net_income = pl["net_income"]
    taxable_income = max(0.0, net_income)
    federal_tax = round(taxable_income * CORPORATE_FEDERAL_RATE, 2)
    return {
        "start_date": pl["start_date"],
        "end_date": pl["end_date"],
        "total_revenue": pl["total_revenue"],
        "total_expenses": pl["total_expenses"],
        "net_income": net_income,
        "taxable_income": round(taxable_income, 2),
        "federal_tax_estimate": federal_tax,
        "rate": CORPORATE_FEDERAL_RATE,
        "disclaimer": "Estimate only. Not legal or tax advice.",
    }


BUDGET_PERIODS = {"annual", "q1", "q2", "q3", "q4", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}


_PERIOD_MONTHS = {
    "annual": list(range(1, 13)),
    "q1": [1, 2, 3], "q2": [4, 5, 6], "q3": [7, 8, 9], "q4": [10, 11, 12],
    "jan": [1], "feb": [2], "mar": [3], "apr": [4], "may": [5], "jun": [6],
    "jul": [7], "aug": [8], "sep": [9], "oct": [10], "nov": [11], "dec": [12],
}


def list_budgets(business_id: int, fiscal_year: int | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = """SELECT budgets.*, accounts.code AS account_code, accounts.name AS account_name, accounts.account_type
            FROM budgets JOIN accounts ON accounts.id = budgets.account_id
            WHERE budgets.business_id = ?"""
        params: list[Any] = [business_id]
        if fiscal_year is not None:
            query += " AND budgets.fiscal_year = ?"
            params.append(fiscal_year)
        query += " ORDER BY budgets.fiscal_year DESC, accounts.code"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_budget(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    try:
        account_id = int(data.get("account_id"))
    except (TypeError, ValueError):
        raise ValueError("account_id is required")
    try:
        fiscal_year = int(data.get("fiscal_year"))
    except (TypeError, ValueError):
        raise ValueError("fiscal_year is required")
    if fiscal_year < 1900 or fiscal_year > 2100:
        raise ValueError("fiscal_year must be a valid year")
    period = str(data.get("period", "annual")).strip().lower()
    if period not in BUDGET_PERIODS:
        raise ValueError("Invalid period")
    budgeted_amount = _money(data.get("budgeted_amount"), "budgeted_amount")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        account = conn.execute("SELECT account_type FROM accounts WHERE id = ? AND business_id = ? AND active = 1", (account_id, business_id)).fetchone()
        if account is None:
            raise ValueError("Account not found for this business")
        try:
            cursor = conn.execute(
                "INSERT INTO budgets (business_id, account_id, fiscal_year, period, budgeted_amount, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (business_id, account_id, fiscal_year, period, budgeted_amount, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Budget already exists for this account, year, and period")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM budgets WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_budget(budget_id: int, data: dict[str, Any]) -> dict[str, Any]:
    budgeted_amount = _money(data.get("budgeted_amount"), "budgeted_amount")
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM budgets WHERE id = ?", (budget_id,)).fetchone()
        if row is None:
            raise ValueError("Budget not found")
        conn.execute("UPDATE budgets SET budgeted_amount = ?, updated_at = ? WHERE id = ?", (budgeted_amount, now, budget_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM budgets WHERE id = ?", (budget_id,)).fetchone())


def delete_budget(budget_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM budgets WHERE id = ?", (budget_id,)).fetchone() is None:
            raise ValueError("Budget not found")
        conn.execute("DELETE FROM budgets WHERE id = ?", (budget_id,))
        conn.commit()


def budget_vs_actual(business_id: int, fiscal_year: int) -> dict[str, Any]:
    """Compare budgeted amounts against posted journal entries for a fiscal year.

    Actuals are derived from posted journal lines, using the same sign
    convention as the P&L: revenue is credit-normal (credits - debits),
    expenses are debit-normal (debits - credits).
    """
    with get_db() as conn:
        _require_business(conn, business_id)
        start_date = f"{fiscal_year}-01-01"
        end_date = f"{fiscal_year}-12-31"
        balances = _account_balances(conn, business_id, end_date, start_date)
        budgets = [row_to_dict(row) for row in conn.execute(
            """SELECT budgets.*, accounts.code AS account_code, accounts.name AS account_name, accounts.account_type
            FROM budgets JOIN accounts ON accounts.id = budgets.account_id
            WHERE budgets.business_id = ? AND budgets.fiscal_year = ? AND budgets.period = 'annual'
            ORDER BY accounts.code""",
            (business_id, fiscal_year),
        ).fetchall()]

    balance_map = {row["id"]: row for row in balances}
    lines = []
    for budget in budgets:
        acct = balance_map.get(budget["account_id"], {"debits": 0, "credits": 0})
        if budget["account_type"] == "revenue":
            actual = round(acct["credits"] - acct["debits"], 2)
        elif budget["account_type"] == "expense":
            actual = round(acct["debits"] - acct["credits"], 2)
        else:
            actual = round(acct["debits"] - acct["credits"], 2)
        budgeted = budget["budgeted_amount"]
        variance = round(budgeted - actual, 2)
        lines.append({
            "account_id": budget["account_id"],
            "account_code": budget["account_code"],
            "account_name": budget["account_name"],
            "account_type": budget["account_type"],
            "budgeted": budgeted,
            "actual": actual,
            "variance": variance,
            "over_budget": actual > budgeted if budgeted > 0 else False,
        })
    total_budgeted = round(sum(line["budgeted"] for line in lines), 2)
    total_actual = round(sum(line["actual"] for line in lines), 2)
    return {
        "fiscal_year": fiscal_year,
        "lines": lines,
        "total_budgeted": total_budgeted,
        "total_actual": total_actual,
        "total_variance": round(total_budgeted - total_actual, 2),
    }


def budget_variance_alerts(business_id: int, fiscal_year: int, threshold_percent: float = 80.0) -> dict[str, Any]:
    """Check budgets against actual spending and return alerts for accounts that exceed or approach their budget."""
    if threshold_percent < 0 or threshold_percent > 100:
        raise ValueError("threshold_percent must be between 0 and 100")
    with get_db() as conn:
        _require_business(conn, business_id)
        budgets = conn.execute(
            "SELECT * FROM budgets WHERE business_id = ? AND fiscal_year = ?",
            (business_id, fiscal_year),
        ).fetchall()
        if not budgets:
            return {"fiscal_year": fiscal_year, "alerts": [], "total_budget": 0, "total_actual": 0}
        alerts: list[dict[str, Any]] = []
        total_budget = 0.0
        total_actual = 0.0
        for budget in budgets:
            budget = row_to_dict(budget)
            # Get actual spending for this account in this period
            period_start = f"{fiscal_year}-01-01"
            period_end = f"{fiscal_year}-12-31"
            actual_rows = conn.execute(
                """SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS actual
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   JOIN accounts a ON a.id = jl.account_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND je.entry_date >= ? AND je.entry_date <= ?
                   AND a.id = ? AND a.account_type = 'expense'""",
                (business_id, period_start, period_end, budget["account_id"]),
            ).fetchone()
            actual = round(actual_rows["actual"], 2)
            budgeted = round(budget["budgeted_amount"], 2)
            total_budget = round(total_budget + budgeted, 2)
            total_actual = round(total_actual + actual, 2)
            if budgeted <= 0:
                continue
            pct_used = round((actual / budgeted) * 100, 2)
            alert_level = None
            if actual > budgeted:
                alert_level = "over_budget"
            elif pct_used >= threshold_percent:
                alert_level = "approaching"
            if alert_level:
                # Get account info
                acct = conn.execute("SELECT code, name FROM accounts WHERE id = ?", (budget["account_id"],)).fetchone()
                alerts.append({
                    "budget_id": budget["id"],
                    "account_id": budget["account_id"],
                    "account_code": acct["code"] if acct else "",
                    "account_name": acct["name"] if acct else "",
                    "period": budget["period"],
                    "budgeted": budgeted,
                    "actual": actual,
                    "variance": round(budgeted - actual, 2),
                    "percent_used": pct_used,
                    "alert_level": alert_level,
                })
        alerts.sort(key=lambda a: a["percent_used"], reverse=True)
        total_variance = round(total_budget - total_actual, 2)
        return {
            "fiscal_year": fiscal_year,
            "threshold_percent": threshold_percent,
            "alerts": alerts,
            "total_budget": total_budget,
            "total_actual": total_actual,
            "total_variance": total_variance,
            "total_percent_used": round((total_actual / total_budget * 100) if total_budget > 0 else 0, 2),
        }


def _aging_bucket(days_overdue: int) -> str:
    if days_overdue < 0:
        return "current"
    if days_overdue < 30:
        return "1-30"
    if days_overdue < 60:
        return "31-60"
    if days_overdue < 90:
        return "61-90"
    return "90+"


AGING_BUCKETS = ["current", "1-30", "31-60", "61-90", "90+"]


def accounts_receivable_aging(business_id: int, as_of: str | None = None) -> dict[str, Any]:
    """AR aging: outstanding invoice balances bucketed by days overdue."""
    if as_of:
        as_of = _date(as_of, "as_of")
    else:
        as_of = datetime.date.today().isoformat()
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT invoices.id, invoices.invoice_number, invoices.issue_date, invoices.due_date,
               invoices.amount, invoices.amount_paid, invoices.status,
               accounting_contacts.name AS customer_name
               FROM invoices JOIN accounting_contacts ON accounting_contacts.id = invoices.customer_id
               WHERE invoices.business_id = ? AND invoices.status = 'open'
               ORDER BY invoices.due_date""",
            (business_id,),
        ).fetchall()
    as_of_date = datetime.date.fromisoformat(as_of)
    lines = []
    totals = {bucket: 0.0 for bucket in AGING_BUCKETS}
    for row in rows:
        balance = round(row["amount"] - row["amount_paid"], 2)
        if balance <= 0:
            continue
        due = datetime.date.fromisoformat(row["due_date"])
        days_overdue = (as_of_date - due).days
        bucket = _aging_bucket(days_overdue)
        totals[bucket] = round(totals[bucket] + balance, 2)
        lines.append({
            "invoice_id": row["id"],
            "invoice_number": row["invoice_number"],
            "customer_name": row["customer_name"],
            "issue_date": row["issue_date"],
            "due_date": row["due_date"],
            "amount": row["amount"],
            "amount_paid": row["amount_paid"],
            "balance": balance,
            "days_overdue": days_overdue,
            "bucket": bucket,
        })
    return {"as_of": as_of, "lines": lines, "totals": totals, "total_outstanding": round(sum(totals.values()), 2)}


def accounts_payable_aging(business_id: int, as_of: str | None = None) -> dict[str, Any]:
    """AP aging: outstanding expense balances bucketed by days overdue.

    Expenses are recorded as paid immediately (debit expense, credit cash/AP),
    so this report tracks expenses that were credited to a liability account
    (Accounts Payable) rather than an asset account (Cash/Bank).
    """
    if as_of:
        as_of = _date(as_of, "as_of")
    else:
        as_of = datetime.date.today().isoformat()
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT expenses.id, expenses.expense_date, expenses.reference, expenses.description,
               expenses.amount, expenses.payment_account_id, expenses.vendor_id,
               accounting_contacts.name AS vendor_name,
               accounts.account_type AS payment_account_type
               FROM expenses LEFT JOIN accounting_contacts ON accounting_contacts.id = expenses.vendor_id
               JOIN accounts ON accounts.id = expenses.payment_account_id
               WHERE expenses.business_id = ?
               ORDER BY expenses.expense_date""",
            (business_id,),
        ).fetchall()
    as_of_date = datetime.date.fromisoformat(as_of)
    lines = []
    totals = {bucket: 0.0 for bucket in AGING_BUCKETS}
    for row in rows:
        if row["payment_account_type"] != "liability":
            continue
        expense_date = datetime.date.fromisoformat(row["expense_date"])
        days_overdue = (as_of_date - expense_date).days
        bucket = _aging_bucket(days_overdue)
        totals[bucket] = round(totals[bucket] + row["amount"], 2)
        lines.append({
            "expense_id": row["id"],
            "reference": row["reference"],
            "description": row["description"],
            "vendor_name": row["vendor_name"] or "",
            "expense_date": row["expense_date"],
            "amount": row["amount"],
            "days_overdue": days_overdue,
            "bucket": bucket,
        })
    return {"as_of": as_of, "lines": lines, "totals": totals, "total_outstanding": round(sum(totals.values()), 2)}


def aging_summary(business_id: int, as_of: str | None = None) -> dict[str, Any]:
    """Consolidated aging dashboard combining AR and AP aging summaries."""
    ar = accounts_receivable_aging(business_id, as_of)
    ap = accounts_payable_aging(business_id, as_of)
    ar_total = ar["total_outstanding"]
    ap_total = ap["total_outstanding"]
    net_cash_position = round(ar_total - ap_total, 2)
    # Build bucket comparison
    bucket_summary = []
    for bucket in AGING_BUCKETS:
        bucket_summary.append({
            "bucket": bucket,
            "receivable": ar["totals"][bucket],
            "payable": ap["totals"][bucket],
            "net": round(ar["totals"][bucket] - ap["totals"][bucket], 2),
        })
    return {
        "as_of": ar["as_of"],
        "ar_total": ar_total,
        "ap_total": ap_total,
        "net_cash_position": net_cash_position,
        "ar_invoice_count": len(ar["lines"]),
        "ap_expense_count": len(ap["lines"]),
        "buckets": bucket_summary,
        "ar_totals": ar["totals"],
        "ap_totals": ap["totals"],
    }


def financial_kpis(business_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    """Compute key financial ratios from posted entries.

    Ratios include current ratio, debt-to-equity, profit margin, and
    return on equity. All values are derived from the same posted journal
    entries used by the financial statements.
    """
    pl = profit_and_loss(business_id, start_date, end_date)
    bs = balance_sheet(business_id, end_date)

    total_assets = bs["total_assets"]
    total_liabilities = bs["total_liabilities"]
    total_equity = bs["total_equity"]
    total_revenue = pl["total_revenue"]
    net_income = pl["net_income"]

    current_assets = round(sum(row["amount"] for row in bs["assets"] if row["account_type"] == "asset"), 2)
    current_liabilities = total_liabilities

    current_ratio = round(current_assets / current_liabilities, 2) if current_liabilities > 0 else None
    debt_to_equity = round(total_liabilities / total_equity, 2) if total_equity > 0 else None
    profit_margin = round((net_income / total_revenue) * 100, 2) if total_revenue > 0 else None
    return_on_equity = round((net_income / total_equity) * 100, 2) if total_equity > 0 else None
    asset_turnover = round(total_revenue / total_assets, 2) if total_assets > 0 else None

    return {
        "start_date": pl["start_date"],
        "end_date": pl["end_date"],
        "as_of": bs["as_of"],
        "current_ratio": current_ratio,
        "debt_to_equity": debt_to_equity,
        "profit_margin_pct": profit_margin,
        "return_on_equity_pct": return_on_equity,
        "asset_turnover": asset_turnover,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "total_equity": total_equity,
        "total_revenue": total_revenue,
        "net_income": net_income,
    }


def cash_flow_statement(business_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    """Indirect-method cash flow statement from posted entries.

    Operating activities start from net income and adjust for non-cash
    items by comparing period changes in asset/liability accounts.
    Investing and financing activities are approximated from changes in
    equity and liability accounts. Cash is the sum of asset account
    balances at the period end minus the start.
    """
    start_date = _date(start_date, "start_date")
    end_date = _date(end_date, "end_date")
    if end_date < start_date:
        raise ValueError("end_date cannot be before start_date")

    with get_db() as conn:
        _require_business(conn, business_id)
        # Period balances (for P&L)
        period_balances = _account_balances(conn, business_id, end_date, start_date)
        # Balances at start (for beginning cash)
        pre_start = (datetime.date.fromisoformat(start_date) - datetime.timedelta(days=1)).isoformat()
        start_balances = _account_balances(conn, business_id, pre_start) if pre_start >= "1900-01-01" else []
        # Balances at end (for ending cash)
        end_balances = _account_balances(conn, business_id, end_date)

    def _net(balances, account_type, sign="credit"):
        total = 0.0
        for row in balances:
            if row["account_type"] == account_type:
                if sign == "credit":
                    total += row["credits"] - row["debits"]
                else:
                    total += row["debits"] - row["credits"]
        return round(total, 2)

    # Net income from P&L
    revenue_total = round(sum(max(0, row["credits"] - row["debits"]) for row in period_balances if row["account_type"] == "revenue"), 2)
    expense_total = round(sum(max(0, row["debits"] - row["credits"]) for row in period_balances if row["account_type"] == "expense"), 2)
    net_income = round(revenue_total - expense_total, 2)

    # Cash accounts = all asset accounts (simplified: all assets treated as cash-equivalent for this report)
    def _cash_total(balances):
        return round(sum(row["debits"] - row["credits"] for row in balances if row["account_type"] == "asset"), 2)

    beginning_cash = _cash_total(start_balances)
    ending_cash = _cash_total(end_balances)

    # Changes in non-cash assets (operating adjustments)
    start_assets_non_cash = round(sum(row["debits"] - row["credits"] for row in start_balances if row["account_type"] == "asset"), 2)
    end_assets_non_cash = round(sum(row["debits"] - row["credits"] for row in end_balances if row["account_type"] == "asset"), 2)
    change_in_assets = round(end_assets_non_cash - start_assets_non_cash, 2)

    # Changes in liabilities (operating adjustments)
    start_liabilities = round(sum(row["credits"] - row["debits"] for row in start_balances if row["account_type"] == "liability"), 2)
    end_liabilities = round(sum(row["credits"] - row["debits"] for row in end_balances if row["account_type"] == "liability"), 2)
    change_in_liabilities = round(end_liabilities - start_liabilities, 2)

    # Changes in equity (financing)
    start_equity = round(sum(row["credits"] - row["debits"] for row in start_balances if row["account_type"] == "equity"), 2)
    end_equity = round(sum(row["credits"] - row["debits"] for row in end_balances if row["account_type"] == "equity"), 2)
    change_in_equity = round(end_equity - start_equity, 2)

    operating_adjustments = round(-change_in_assets + change_in_liabilities, 2)
    operating_cash_flow = round(net_income + operating_adjustments, 2)
    investing_cash_flow = round(change_in_assets, 2)  # simplified
    financing_cash_flow = round(change_in_equity + change_in_liabilities, 2)  # simplified

    return {
        "start_date": start_date,
        "end_date": end_date,
        "operating": {
            "net_income": net_income,
            "change_in_assets": -change_in_assets,
            "change_in_liabilities": change_in_liabilities,
            "net_cash": operating_cash_flow,
        },
        "investing": {
            "net_cash": investing_cash_flow,
        },
        "financing": {
            "change_in_equity": change_in_equity,
            "change_in_liabilities": change_in_liabilities,
            "net_cash": financing_cash_flow,
        },
        "beginning_cash": beginning_cash,
        "ending_cash": ending_cash,
        "net_change_in_cash": round(ending_cash - beginning_cash, 2),
    }


def expense_breakdown(business_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    """Break down expenses by account for the period."""
    pl = profit_and_loss(business_id, start_date, end_date)
    expenses = pl["expenses"]
    total = pl["total_expenses"]
    breakdown = []
    for exp in expenses:
        pct = round((exp["amount"] / total) * 100, 2) if total > 0 else 0
        breakdown.append({
            "account_id": exp["id"],
            "account_code": exp["code"],
            "account_name": exp["name"],
            "amount": exp["amount"],
            "percentage": pct,
        })
    breakdown.sort(key=lambda x: x["amount"], reverse=True)
    return {
        "start_date": pl["start_date"],
        "end_date": pl["end_date"],
        "total_expenses": total,
        "breakdown": breakdown,
    }


def multi_year_comparison(business_id: int, years: list[int]) -> dict[str, Any]:
    """Compare P&L across multiple years."""
    results = []
    for year in years:
        start = f"{year}-01-01"
        end = f"{year}-12-31"
        pl = profit_and_loss(business_id, start, end)
        results.append({
            "year": year,
            "total_revenue": pl["total_revenue"],
            "total_expenses": pl["total_expenses"],
            "net_income": pl["net_income"],
        })
    return {"years": results}


def financial_ratios(business_id: int, as_of_date: str | None = None) -> dict[str, Any]:
    """Calculate key financial ratios from posted entries."""
    import datetime
    if as_of_date is None:
        as_of_date = datetime.date.today().isoformat()
    with get_db() as conn:
        _require_business(conn, business_id)
        # Get balances by account type as of as_of_date
        rows = conn.execute(
            """SELECT a.account_type,
                   ROUND(COALESCE(SUM(CASE WHEN je.status = 'posted' AND je.entry_date <= ? THEN jl.debit ELSE 0 END), 0), 2) AS total_debits,
                   ROUND(COALESCE(SUM(CASE WHEN je.status = 'posted' AND je.entry_date <= ? THEN jl.credit ELSE 0 END), 0), 2) AS total_credits
               FROM accounts a
               LEFT JOIN journal_lines jl ON jl.account_id = a.id
               LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.business_id = a.business_id
               WHERE a.business_id = ?
               GROUP BY a.account_type""",
            (as_of_date, as_of_date, business_id),
        ).fetchall()
        balances: dict[str, float] = {"asset": 0.0, "liability": 0.0, "equity": 0.0, "revenue": 0.0, "expense": 0.0}
        for row in rows:
            atype = row["account_type"]
            if atype in ("asset", "expense"):
                balances[atype] = round(row["total_debits"] - row["total_credits"], 2)
            else:
                balances[atype] = round(row["total_credits"] - row["total_debits"], 2)
        total_assets = balances["asset"]
        total_liabilities = balances["liability"]
        total_equity = balances["equity"]
        total_revenue = balances["revenue"]
        total_expenses = balances["expense"]
        net_income = round(total_revenue - total_expenses, 2)

        # Current assets (asset accounts, simplified: all assets)
        current_assets = total_assets
        # Current liabilities (simplified: all liabilities)
        current_liabilities = total_liabilities

        ratios: dict[str, Any] = {
            "as_of_date": as_of_date,
            "balances": {
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "total_revenue": total_revenue,
                "total_expenses": total_expenses,
                "net_income": net_income,
            },
            "current_ratio": round(current_assets / current_liabilities, 2) if current_liabilities > 0 else None,
            "quick_ratio": round((current_assets * 0.9) / current_liabilities, 2) if current_liabilities > 0 else None,
            "debt_ratio": round(total_liabilities / total_assets, 2) if total_assets > 0 else None,
            "debt_to_equity": round(total_liabilities / total_equity, 2) if total_equity > 0 else None,
            "equity_ratio": round(total_equity / total_assets, 2) if total_assets > 0 else None,
            "return_on_assets": round((net_income / total_assets) * 100, 2) if total_assets > 0 else None,
            "return_on_equity": round((net_income / total_equity) * 100, 2) if total_equity > 0 else None,
            "profit_margin": round((net_income / total_revenue) * 100, 2) if total_revenue > 0 else None,
            "asset_turnover": round(total_revenue / total_assets, 2) if total_assets > 0 else None,
        }
        return ratios


def cash_flow_forecast(business_id: int, months: int = 3) -> dict[str, Any]:
    """Forecast cash flow based on outstanding receivables, payables, and recurring expenses."""
    import datetime
    if months < 1 or months > 12:
        raise ValueError("months must be between 1 and 12")
    with get_db() as conn:
        _require_business(conn, business_id)
        today = datetime.date.today()
        # Get outstanding receivables from open invoices
        inv_rows = conn.execute(
            """SELECT invoices.due_date, invoices.amount, invoices.amount_paid
               FROM invoices WHERE business_id = ? AND status = 'open'
               ORDER BY due_date""",
            (business_id,),
        ).fetchall()
        # Get outstanding payables from expenses paid with liability accounts
        exp_rows = conn.execute(
            """SELECT expenses.expense_date, expenses.amount, expenses.payment_account_id,
               accounts.account_type AS payment_account_type
               FROM expenses JOIN accounts ON accounts.id = expenses.payment_account_id
               WHERE expenses.business_id = ?
               ORDER BY expenses.expense_date""",
            (business_id,),
        ).fetchall()
        # Get recurring expenses
        recurring_rows = conn.execute(
            """SELECT * FROM recurring_expenses WHERE business_id = ? AND active = 1""",
            (business_id,),
        ).fetchall()
        # Project every scheduled recurring occurrence into its forecast month
        # using the same anchored generator as posting. Occurrences overdue
        # before the first forecast month count in month 0 (they are due now).
        month_0 = today.replace(day=1)
        horizon_end = _add_months(month_0, months) - datetime.timedelta(days=1)
        recurring_outflows = [0.0] * months
        for rec in recurring_rows:
            rec = row_to_dict(rec)
            for occ_str in _iter_occurrences(rec["start_date"], rec["frequency"], first=rec["next_date"]):
                if rec["end_date"] and occ_str > rec["end_date"]:
                    break
                occ = datetime.date.fromisoformat(occ_str)
                if occ > horizon_end:
                    break
                idx = (occ.year - month_0.year) * 12 + (occ.month - month_0.month)
                recurring_outflows[max(0, idx)] += rec["amount"]
        # Build monthly forecast
        forecast: list[dict[str, Any]] = []
        for m in range(months):
            month_date = today.replace(day=1)
            for _ in range(m):
                if month_date.month == 12:
                    month_date = month_date.replace(year=month_date.year + 1, month=1)
                else:
                    month_date = month_date.replace(month=month_date.month + 1)
            month_end = month_date.replace(day=28) if month_date.month == 2 else month_date.replace(day=30)
            month_key = month_date.isoformat()[:7]
            inflows = 0.0
            outflows = 0.0
            # Receivables due in this month
            for inv in inv_rows:
                balance = round(inv["amount"] - inv["amount_paid"], 2)
                if balance <= 0:
                    continue
                due = datetime.date.fromisoformat(inv["due_date"])
                if month_date <= due.replace(day=1) <= month_end:
                    inflows = round(inflows + balance, 2)
            # Payables due in this month
            for exp in exp_rows:
                if exp["payment_account_type"] != "liability":
                    continue
                exp_date = datetime.date.fromisoformat(exp["expense_date"])
                if month_date <= exp_date.replace(day=1) <= month_end:
                    outflows = round(outflows + exp["amount"], 2)
            # Recurring expenses due in this month
            outflows = round(outflows + recurring_outflows[m], 2)
            net = round(inflows - outflows, 2)
            forecast.append({
                "month": month_key,
                "expected_inflows": inflows,
                "expected_outflows": outflows,
                "net_cash_flow": net,
            })
        total_inflows = round(sum(f["expected_inflows"] for f in forecast), 2)
        total_outflows = round(sum(f["expected_outflows"] for f in forecast), 2)
        # Get current cash balance from asset accounts
        cash_rows = conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jl.debit - jl.credit ELSE 0 END), 0) AS balance
               FROM accounts a
               LEFT JOIN journal_lines jl ON jl.account_id = a.id
               LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.business_id = a.business_id
               WHERE a.business_id = ? AND a.account_type = 'asset' AND a.code LIKE '1%'""",
            (business_id,),
        ).fetchone()
        current_cash = round(cash_rows["balance"], 2)
        projected_ending = round(current_cash + total_inflows - total_outflows, 2)
        return {
            "current_cash_balance": current_cash,
            "forecast_months": months,
            "monthly_forecast": forecast,
            "total_expected_inflows": total_inflows,
            "total_expected_outflows": total_outflows,
            "projected_net_cash_flow": round(total_inflows - total_outflows, 2),
            "projected_ending_balance": projected_ending,
        }


def dashboard_summary(business_id: int) -> dict[str, Any]:
    """Cross-module dashboard combining key metrics from all accounting subsystems."""
    with get_db() as conn:
        _require_business(conn, business_id)
        # Cash balance (asset accounts starting with code 1)
        cash_row = conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN je.status = 'posted' THEN jl.debit - jl.credit ELSE 0 END), 0) AS balance
               FROM accounts a
               LEFT JOIN journal_lines jl ON jl.account_id = a.id
               LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.business_id = a.business_id
               WHERE a.business_id = ? AND a.account_type = 'asset' AND a.code LIKE '1%'""",
            (business_id,),
        ).fetchone()
        cash_balance = round(cash_row["balance"], 2)
        # Open invoices
        inv_row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount - amount_paid), 0) AS outstanding FROM invoices WHERE business_id = ? AND status = 'open'",
            (business_id,),
        ).fetchone()
        open_invoices = inv_row["cnt"]
        outstanding_receivables = round(inv_row["outstanding"], 2)
        # Pending expenses
        pending_row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS total FROM expenses WHERE business_id = ? AND approval_status = 'pending'",
            (business_id,),
        ).fetchone()
        pending_expenses = pending_row["cnt"]
        pending_expense_total = round(pending_row["total"], 2)
        # Total expenses (this year)
        import datetime
        year_start = f"{datetime.date.today().year}-01-01"
        exp_row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE business_id = ? AND approval_status = 'approved' AND expense_date >= ?",
            (business_id, year_start),
        ).fetchone()
        total_expenses_ytd = round(exp_row["total"], 2)
        # Revenue (this year from posted entries to revenue accounts)
        rev_row = conn.execute(
            """SELECT COALESCE(SUM(CASE WHEN je.status = 'posted' AND je.entry_date >= ? THEN jl.credit - jl.debit ELSE 0 END), 0) AS total
               FROM accounts a
               LEFT JOIN journal_lines jl ON jl.account_id = a.id
               LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.business_id = a.business_id
               WHERE a.business_id = ? AND a.account_type = 'revenue'""",
            (year_start, business_id),
        ).fetchone()
        total_revenue_ytd = round(rev_row["total"], 2)
        net_income_ytd = round(total_revenue_ytd - total_expenses_ytd, 2)
        # 1099 vendors
        vendors_1099 = conn.execute(
            "SELECT COUNT(*) AS cnt FROM accounting_contacts WHERE business_id = ? AND is_1099 = 1",
            (business_id,),
        ).fetchone()["cnt"]
        # Active fixed assets
        assets_row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(cost), 0) AS total FROM depreciation_assets WHERE business_id = ? AND status = 'active'",
            (business_id,),
        ).fetchone()
        active_fixed_assets = assets_row["cnt"]
        fixed_asset_total = round(assets_row["total"], 2)
        # Recent journal entries count (this year)
        entries_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM journal_entries WHERE business_id = ? AND entry_date >= ?",
            (business_id, year_start),
        ).fetchone()
        journal_entries_ytd = entries_row["cnt"]
        # Open purchase orders
        po_row = conn.execute(
            "SELECT COUNT(*) AS cnt, COALESCE(SUM(total_amount), 0) AS total FROM purchase_orders WHERE business_id = ? AND status IN ('draft', 'sent')",
            (business_id,),
        ).fetchone()
        open_purchase_orders = po_row["cnt"]
        po_total = round(po_row["total"], 2)
        # Contacts count
        customers = conn.execute(
            "SELECT COUNT(*) AS cnt FROM accounting_contacts WHERE business_id = ? AND contact_type IN ('customer', 'both')",
            (business_id,),
        ).fetchone()["cnt"]
        vendors = conn.execute(
            "SELECT COUNT(*) AS cnt FROM accounting_contacts WHERE business_id = ? AND contact_type IN ('vendor', 'both')",
            (business_id,),
        ).fetchone()["cnt"]
        # Account count
        accounts = conn.execute(
            "SELECT COUNT(*) AS cnt FROM accounts WHERE business_id = ?",
            (business_id,),
        ).fetchone()["cnt"]
        return {
            "cash_balance": cash_balance,
            "outstanding_receivables": outstanding_receivables,
            "open_invoices": open_invoices,
            "pending_expenses": pending_expenses,
            "pending_expense_total": pending_expense_total,
            "total_revenue_ytd": total_revenue_ytd,
            "total_expenses_ytd": total_expenses_ytd,
            "net_income_ytd": net_income_ytd,
            "vendors_1099": vendors_1099,
            "active_fixed_assets": active_fixed_assets,
            "fixed_asset_total": fixed_asset_total,
            "journal_entries_ytd": journal_entries_ytd,
            "open_purchase_orders": open_purchase_orders,
            "open_po_total": po_total,
            "customer_count": customers,
            "vendor_count": vendors,
            "account_count": accounts,
        }
