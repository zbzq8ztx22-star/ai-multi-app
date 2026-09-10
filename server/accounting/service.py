from __future__ import annotations

import datetime
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from payroll.db import get_db, now_utc, row_to_dict

ACCOUNT_TYPES = {"asset", "liability", "equity", "revenue", "expense"}
ENTRY_STATUSES = {"draft", "posted"}


def _money(value: Any, field: str) -> float:
    try:
        amount = Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field} must be a number")
    if amount < 0:
        raise ValueError(f"{field} cannot be negative")
    return float(amount)


def _require_business(conn: sqlite3.Connection, business_id: int) -> None:
    if conn.execute("SELECT id FROM businesses WHERE id = ?", (business_id,)).fetchone() is None:
        raise ValueError("Business not found")


def list_accounts(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("SELECT * FROM accounts WHERE business_id = ? ORDER BY code", (business_id,)).fetchall()
        return [row_to_dict(row) for row in rows]


def create_account(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    account_type = data.get("account_type")
    if not code or not name:
        raise ValueError("code and name are required")
    if account_type not in ACCOUNT_TYPES:
        raise ValueError("Invalid account_type")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        try:
            cursor = conn.execute(
                "INSERT INTO accounts (business_id, code, name, account_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (business_id, code, name, account_type, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Account code already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM accounts WHERE id = ?", (cursor.lastrowid,)).fetchone())


def _entry_lines(conn: sqlite3.Connection, entry_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT journal_lines.*, accounts.code AS account_code, accounts.name AS account_name
        FROM journal_lines JOIN accounts ON accounts.id = journal_lines.account_id
        WHERE entry_id = ? ORDER BY journal_lines.id""",
        (entry_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def list_entries(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("SELECT * FROM journal_entries WHERE business_id = ? ORDER BY entry_date DESC, id DESC", (business_id,)).fetchall()
        result = []
        for row in rows:
            entry = row_to_dict(row)
            entry["lines"] = _entry_lines(conn, entry["id"])
            result.append(entry)
        return result


def create_entry(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    description = str(data.get("description", "")).strip()
    if not description:
        raise ValueError("description is required")
    try:
        entry_date = datetime.date.fromisoformat(str(data.get("entry_date", ""))).isoformat()
    except ValueError:
        raise ValueError("entry_date must be a valid ISO date")
    status = data.get("status", "posted")
    if status not in ENTRY_STATUSES:
        raise ValueError("Invalid status")
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or len(raw_lines) < 2:
        raise ValueError("At least two journal lines are required")
    lines = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise ValueError("Each journal line must be an object")
        try:
            account_id = int(raw.get("account_id"))
        except (TypeError, ValueError):
            raise ValueError("account_id is required for each line")
        debit = _money(raw.get("debit"), "debit")
        credit = _money(raw.get("credit"), "credit")
        if (debit > 0) == (credit > 0):
            raise ValueError("Each line must have either a debit or a credit")
        lines.append((account_id, str(raw.get("description", "")).strip(), debit, credit))
    debit_cents = sum(round(line[2] * 100) for line in lines)
    credit_cents = sum(round(line[3] * 100) for line in lines)
    if debit_cents != credit_cents:
        raise ValueError("Journal entry is not balanced")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        account_ids = {row["id"] for row in conn.execute("SELECT id FROM accounts WHERE business_id = ? AND active = 1", (business_id,)).fetchall()}
        if any(line[0] not in account_ids for line in lines):
            raise ValueError("All accounts must be active and belong to the business")
        cursor = conn.execute(
            "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (business_id, entry_date, str(data.get("reference", "")).strip(), description, status, now, now),
        )
        entry_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
            [(entry_id, *line) for line in lines],
        )
        conn.commit()
        entry = row_to_dict(conn.execute("SELECT * FROM journal_entries WHERE id = ?", (entry_id,)).fetchone())
        entry["lines"] = _entry_lines(conn, entry_id)
        return entry


def trial_balance(business_id: int) -> dict[str, Any]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT accounts.id, accounts.code, accounts.name, accounts.account_type,
            ROUND(COALESCE(SUM(CASE WHEN journal_entries.status = 'posted' THEN journal_lines.debit ELSE 0 END), 0), 2) AS debits,
            ROUND(COALESCE(SUM(CASE WHEN journal_entries.status = 'posted' THEN journal_lines.credit ELSE 0 END), 0), 2) AS credits
            FROM accounts LEFT JOIN journal_lines ON journal_lines.account_id = accounts.id
            LEFT JOIN journal_entries ON journal_entries.id = journal_lines.entry_id
            WHERE accounts.business_id = ? GROUP BY accounts.id ORDER BY accounts.code""",
            (business_id,),
        ).fetchall()
        accounts = [row_to_dict(row) for row in rows]
        total_debits = round(sum(row["debits"] for row in accounts), 2)
        total_credits = round(sum(row["credits"] for row in accounts), 2)
        return {"accounts": accounts, "total_debits": total_debits, "total_credits": total_credits, "balanced": total_debits == total_credits}


def general_ledger(business_id: int, account_id: int | None = None) -> list[dict[str, Any]]:
    query = """SELECT journal_entries.entry_date, journal_entries.reference, journal_entries.description AS entry_description,
        accounts.id AS account_id, accounts.code AS account_code, accounts.name AS account_name,
        journal_lines.description, journal_lines.debit, journal_lines.credit
        FROM journal_lines JOIN journal_entries ON journal_entries.id = journal_lines.entry_id
        JOIN accounts ON accounts.id = journal_lines.account_id
        WHERE journal_entries.business_id = ? AND journal_entries.status = 'posted'"""
    params: list[Any] = [business_id]
    if account_id is not None:
        query += " AND accounts.id = ?"
        params.append(account_id)
    query += " ORDER BY journal_entries.entry_date, journal_entries.id, journal_lines.id"
    with get_db() as conn:
        _require_business(conn, business_id)
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def _date(value: Any, field: str) -> str:
    try:
        return datetime.date.fromisoformat(str(value or "")).isoformat()
    except ValueError:
        raise ValueError(f"{field} must be a valid ISO date")


def _account_for_business(conn: sqlite3.Connection, business_id: int, account_id: Any, allowed_types: set[str], field: str) -> int:
    try:
        account_id = int(account_id)
    except (TypeError, ValueError):
        raise ValueError(f"{field} is required")
    row = conn.execute("SELECT account_type FROM accounts WHERE id = ? AND business_id = ? AND active = 1", (account_id, business_id)).fetchone()
    if row is None or row["account_type"] not in allowed_types:
        raise ValueError(f"{field} must be an active {', '.join(sorted(allowed_types))} account for this business")
    return account_id


def _post_operation_entry(conn: sqlite3.Connection, business_id: int, entry_date: str, reference: str, description: str, lines: list[tuple[int, float, float]]) -> int:
    now = now_utc()
    cursor = conn.execute(
        "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'posted', ?, ?)",
        (business_id, entry_date, reference, description, now, now),
    )
    entry_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO journal_lines (entry_id, account_id, debit, credit) VALUES (?, ?, ?, ?)",
        [(entry_id, account_id, debit, credit) for account_id, debit, credit in lines],
    )
    return entry_id


def list_contacts(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        return [row_to_dict(row) for row in conn.execute("SELECT * FROM accounting_contacts WHERE business_id = ? ORDER BY name", (business_id,)).fetchall()]


def create_contact(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    name = str(data.get("name", "")).strip()
    contact_type = data.get("contact_type", "customer")
    if not name:
        raise ValueError("name is required")
    if contact_type not in {"customer", "vendor", "both"}:
        raise ValueError("Invalid contact_type")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        cursor = conn.execute(
            "INSERT INTO accounting_contacts (business_id, name, contact_type, email, phone, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (business_id, name, contact_type, str(data.get("email", "")).strip(), str(data.get("phone", "")).strip(), now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM accounting_contacts WHERE id = ?", (cursor.lastrowid,)).fetchone())


def list_invoices(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("""SELECT invoices.*, accounting_contacts.name AS customer_name
            FROM invoices JOIN accounting_contacts ON accounting_contacts.id = invoices.customer_id
            WHERE invoices.business_id = ? ORDER BY issue_date DESC, id DESC""", (business_id,)).fetchall()
        return [row_to_dict(row) for row in rows]


def create_invoice(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id")); customer_id = int(data.get("customer_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id and customer_id are required")
    number = str(data.get("invoice_number", "")).strip()
    description = str(data.get("description", "")).strip()
    amount = _money(data.get("amount"), "amount")
    if not number or not description or amount <= 0:
        raise ValueError("invoice_number, description and a positive amount are required")
    issue_date = _date(data.get("issue_date"), "issue_date")
    due_date = _date(data.get("due_date"), "due_date")
    if due_date < issue_date:
        raise ValueError("due_date cannot be before issue_date")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        contact = conn.execute("SELECT contact_type FROM accounting_contacts WHERE id = ? AND business_id = ?", (customer_id, business_id)).fetchone()
        if contact is None or contact["contact_type"] not in ("customer", "both"):
            raise ValueError("Customer not found for this business")
        receivable = _account_for_business(conn, business_id, data.get("receivable_account_id"), {"asset"}, "receivable_account_id")
        revenue = _account_for_business(conn, business_id, data.get("revenue_account_id"), {"revenue"}, "revenue_account_id")
        entry_id = _post_operation_entry(conn, business_id, issue_date, number, description, [(receivable, amount, 0), (revenue, 0, amount)])
        try:
            cursor = conn.execute("""INSERT INTO invoices
                (business_id, customer_id, invoice_number, issue_date, due_date, description, amount,
                 receivable_account_id, revenue_account_id, journal_entry_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (business_id, customer_id, number, issue_date, due_date, description, amount, receivable, revenue, entry_id, now, now))
        except sqlite3.IntegrityError:
            raise ValueError("Invoice number already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (cursor.lastrowid,)).fetchone())


def record_payment(data: dict[str, Any]) -> dict[str, Any]:
    try:
        invoice_id = int(data.get("invoice_id"))
    except (TypeError, ValueError):
        raise ValueError("invoice_id is required")
    amount = _money(data.get("amount"), "amount")
    if amount <= 0:
        raise ValueError("amount must be positive")
    payment_date = _date(data.get("payment_date"), "payment_date")
    now = now_utc()
    with get_db() as conn:
        invoice = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if invoice is None or invoice["status"] != "open":
            raise ValueError("Open invoice not found")
        balance = round(invoice["amount"] - invoice["amount_paid"], 2)
        if amount > balance:
            raise ValueError("Payment cannot exceed invoice balance")
        cash = _account_for_business(conn, invoice["business_id"], data.get("cash_account_id"), {"asset"}, "cash_account_id")
        entry_id = _post_operation_entry(conn, invoice["business_id"], payment_date, invoice["invoice_number"], "Invoice payment", [(cash, amount, 0), (invoice["receivable_account_id"], 0, amount)])
        cursor = conn.execute("INSERT INTO invoice_payments (invoice_id, payment_date, amount, cash_account_id, journal_entry_id, created_at) VALUES (?, ?, ?, ?, ?, ?)", (invoice_id, payment_date, amount, cash, entry_id, now))
        paid = round(invoice["amount_paid"] + amount, 2)
        conn.execute("UPDATE invoices SET amount_paid = ?, status = ?, updated_at = ? WHERE id = ?", (paid, "paid" if paid == invoice["amount"] else "open", now, invoice_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM invoice_payments WHERE id = ?", (cursor.lastrowid,)).fetchone())


def list_expenses(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("""SELECT expenses.*, accounting_contacts.name AS vendor_name FROM expenses
            LEFT JOIN accounting_contacts ON accounting_contacts.id = expenses.vendor_id
            WHERE expenses.business_id = ? ORDER BY expense_date DESC, id DESC""", (business_id,)).fetchall()
        return [row_to_dict(row) for row in rows]


def create_expense(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    amount = _money(data.get("amount"), "amount")
    description = str(data.get("description", "")).strip()
    if amount <= 0 or not description:
        raise ValueError("description and a positive amount are required")
    expense_date = _date(data.get("expense_date"), "expense_date")
    vendor_id = data.get("vendor_id") or None
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if vendor_id:
            contact = conn.execute("SELECT contact_type FROM accounting_contacts WHERE id = ? AND business_id = ?", (vendor_id, business_id)).fetchone()
            if contact is None or contact["contact_type"] not in ("vendor", "both"):
                raise ValueError("Vendor not found for this business")
        expense_account = _account_for_business(conn, business_id, data.get("expense_account_id"), {"expense"}, "expense_account_id")
        payment_account = _account_for_business(conn, business_id, data.get("payment_account_id"), {"asset", "liability"}, "payment_account_id")
        reference = str(data.get("reference", "")).strip()
        entry_id = _post_operation_entry(conn, business_id, expense_date, reference, description, [(expense_account, amount, 0), (payment_account, 0, amount)])
        cursor = conn.execute("""INSERT INTO expenses
            (business_id, vendor_id, expense_date, reference, description, amount, expense_account_id, payment_account_id, journal_entry_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (business_id, vendor_id, expense_date, reference, description, amount, expense_account, payment_account, entry_id, now))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (cursor.lastrowid,)).fetchone())


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


# Federal corporate income tax estimate. This is a simplified flat-rate
# estimate for planning purposes only and is not legal or tax advice.
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
