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
        cost_center_id = raw.get("cost_center_id")
        if cost_center_id is not None:
            cost_center_id = int(cost_center_id)
        lines.append((account_id, str(raw.get("description", "")).strip(), debit, credit, cost_center_id))
    debit_cents = sum(round(line[2] * 100) for line in lines)
    credit_cents = sum(round(line[3] * 100) for line in lines)
    if debit_cents != credit_cents:
        raise ValueError("Journal entry is not balanced")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if _is_period_closed(conn, business_id, entry_date):
            raise ValueError("Cannot post to a closed accounting period")
        account_ids = {row["id"] for row in conn.execute("SELECT id FROM accounts WHERE business_id = ? AND active = 1", (business_id,)).fetchall()}
        if any(line[0] not in account_ids for line in lines):
            raise ValueError("All accounts must be active and belong to the business")
        cursor = conn.execute(
            "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (business_id, entry_date, str(data.get("reference", "")).strip(), description, status, now, now),
        )
        entry_id = cursor.lastrowid
        conn.executemany(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit, cost_center_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(entry_id, line[0], line[1], line[2], line[3], line[4]) for line in lines],
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


def get_invoice_detail(invoice_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute(
            """SELECT invoices.*, accounting_contacts.name AS customer_name,
               accounting_contacts.email AS customer_email,
               businesses.legal_name AS business_name,
               businesses.dba_name AS business_dba
               FROM invoices
               JOIN accounting_contacts ON accounting_contacts.id = invoices.customer_id
               JOIN businesses ON businesses.id = invoices.business_id
               WHERE invoices.id = ?""",
            (invoice_id,),
        ).fetchone()
        if row is None:
            return None
        return row_to_dict(row)


def void_invoice(invoice_id: int) -> dict[str, Any]:
    """Void an open invoice by setting status to 'void'.

    This does not reverse the journal entry; it simply marks the invoice
    as void so it no longer appears in AR aging reports.
    """
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        if row is None:
            raise ValueError("Invoice not found")
        if row["status"] != "open":
            raise ValueError("Only open invoices can be voided")
        conn.execute("UPDATE invoices SET status = 'void', updated_at = ? WHERE id = ?", (now, invoice_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone())


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
    net_change = round(operating_cash_flow + investing_cash_flow + financing_cash_flow, 2)

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


RECONCILIATION_STATUSES = {"open", "reconciled", "discrepancy"}


def list_reconciliations(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT reconciliations.*, accounts.code AS account_code, accounts.name AS account_name
            FROM reconciliations JOIN accounts ON accounts.id = reconciliations.account_id
            WHERE reconciliations.business_id = ? ORDER BY statement_date DESC, id DESC""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_reconciliation(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    try:
        account_id = int(data.get("account_id"))
    except (TypeError, ValueError):
        raise ValueError("account_id is required")
    statement_date = _date(data.get("statement_date"), "statement_date")
    statement_balance = _money(data.get("statement_balance"), "statement_balance")
    notes = str(data.get("notes", "")).strip()
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        account = conn.execute("SELECT account_type FROM accounts WHERE id = ? AND business_id = ? AND active = 1", (account_id, business_id)).fetchone()
        if account is None:
            raise ValueError("Account not found for this business")
        # Compute book balance from posted entries up to statement_date
        balances = _account_balances(conn, business_id, statement_date)
        acct_balance = next((row for row in balances if row["id"] == account_id), None)
        if acct_balance is None:
            book_balance = 0.0
        elif account["account_type"] in ("asset", "expense"):
            book_balance = round(acct_balance["debits"] - acct_balance["credits"], 2)
        else:
            book_balance = round(acct_balance["credits"] - acct_balance["debits"], 2)
        difference = round(statement_balance - book_balance, 2)
        status = "reconciled" if abs(difference) < 0.005 else "discrepancy"
        cursor = conn.execute(
            "INSERT INTO reconciliations (business_id, account_id, statement_date, statement_balance, book_balance, difference, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (business_id, account_id, statement_date, statement_balance, book_balance, difference, status, notes, now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM reconciliations WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_reconciliation(reconciliation_id: int, data: dict[str, Any]) -> dict[str, Any]:
    notes = str(data.get("notes", "")).strip()
    status = str(data.get("status", "")).strip().lower()
    if status and status not in RECONCILIATION_STATUSES:
        raise ValueError("Invalid status")
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reconciliations WHERE id = ?", (reconciliation_id,)).fetchone()
        if row is None:
            raise ValueError("Reconciliation not found")
        if status:
            conn.execute("UPDATE reconciliations SET status = ?, notes = ?, updated_at = ? WHERE id = ?", (status, notes, now, reconciliation_id))
        else:
            conn.execute("UPDATE reconciliations SET notes = ?, updated_at = ? WHERE id = ?", (notes, now, reconciliation_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM reconciliations WHERE id = ?", (reconciliation_id,)).fetchone())


def delete_reconciliation(reconciliation_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM reconciliations WHERE id = ?", (reconciliation_id,)).fetchone() is None:
            raise ValueError("Reconciliation not found")
        conn.execute("DELETE FROM reconciliations WHERE id = ?", (reconciliation_id,))
        conn.commit()


RECURRING_FREQUENCIES = {"weekly", "monthly", "quarterly", "yearly"}


def _advance_date(date_str: str, frequency: str) -> str:
    d = datetime.date.fromisoformat(date_str)
    if frequency == "weekly":
        d += datetime.timedelta(weeks=1)
    elif frequency == "monthly":
        month = d.month + 1
        year = d.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        d = d.replace(year=year, month=month)
    elif frequency == "quarterly":
        month = d.month + 3
        year = d.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        d = d.replace(year=year, month=month)
    elif frequency == "yearly":
        d = d.replace(year=d.year + 1)
    return d.isoformat()


def list_recurring_expenses(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT recurring_expenses.*, accounts.code AS expense_code, accounts.name AS expense_name,
               pa.code AS payment_code, pa.name AS payment_name,
               accounting_contacts.name AS vendor_name
               FROM recurring_expenses
               JOIN accounts ON accounts.id = recurring_expenses.expense_account_id
               JOIN accounts pa ON pa.id = recurring_expenses.payment_account_id
               LEFT JOIN accounting_contacts ON accounting_contacts.id = recurring_expenses.vendor_id
               WHERE recurring_expenses.business_id = ?
               ORDER BY recurring_expenses.next_date, recurring_expenses.id""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_recurring_expense(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    description = str(data.get("description", "")).strip()
    amount = _money(data.get("amount"), "amount")
    if not description or amount <= 0:
        raise ValueError("description and a positive amount are required")
    frequency = str(data.get("frequency", "")).strip().lower()
    if frequency not in RECURRING_FREQUENCIES:
        raise ValueError("frequency must be one of: weekly, monthly, quarterly, yearly")
    start_date = _date(data.get("start_date"), "start_date")
    end_date = data.get("end_date")
    if end_date:
        end_date = _date(end_date, "end_date")
        if end_date < start_date:
            raise ValueError("end_date cannot be before start_date")
    vendor_id = data.get("vendor_id")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        expense_account = _account_for_business(conn, business_id, data.get("expense_account_id"), {"expense"}, "expense_account_id")
        payment_account = _account_for_business(conn, business_id, data.get("payment_account_id"), {"asset", "liability"}, "payment_account_id")
        if vendor_id:
            vendor = conn.execute("SELECT id FROM accounting_contacts WHERE id = ? AND business_id = ? AND contact_type IN ('vendor', 'both')", (vendor_id, business_id)).fetchone()
            if vendor is None:
                raise ValueError("Vendor not found for this business")
        cursor = conn.execute(
            """INSERT INTO recurring_expenses
            (business_id, vendor_id, description, amount, expense_account_id, payment_account_id,
             frequency, start_date, next_date, end_date, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (business_id, vendor_id, description, amount, expense_account, payment_account,
             frequency, start_date, start_date, end_date, now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM recurring_expenses WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_recurring_expense(recurring_id: int, data: dict[str, Any]) -> dict[str, Any]:
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM recurring_expenses WHERE id = ?", (recurring_id,)).fetchone()
        if row is None:
            raise ValueError("Recurring expense not found")
        updates = {}
        if "description" in data:
            desc = str(data["description"]).strip()
            if not desc:
                raise ValueError("description cannot be empty")
            updates["description"] = desc
        if "amount" in data:
            updates["amount"] = _money(data["amount"], "amount")
            if updates["amount"] <= 0:
                raise ValueError("amount must be positive")
        if "frequency" in data:
            freq = str(data["frequency"]).strip().lower()
            if freq not in RECURRING_FREQUENCIES:
                raise ValueError("Invalid frequency")
            updates["frequency"] = freq
        if "active" in data:
            updates["active"] = 1 if data["active"] else 0
        if "end_date" in data and data["end_date"]:
            updates["end_date"] = _date(data["end_date"], "end_date")
        updates["updated_at"] = now
        if updates:
            cols = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(f"UPDATE recurring_expenses SET {cols} WHERE id = ?", (*updates.values(), recurring_id))
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM recurring_expenses WHERE id = ?", (recurring_id,)).fetchone())


def delete_recurring_expense(recurring_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM recurring_expenses WHERE id = ?", (recurring_id,)).fetchone() is None:
            raise ValueError("Recurring expense not found")
        conn.execute("DELETE FROM recurring_expenses WHERE id = ?", (recurring_id,))
        conn.commit()


def post_due_recurring_expenses(business_id: int, as_of: str | None = None) -> list[dict[str, Any]]:
    """Post all recurring expenses that are due on or before as_of."""
    if as_of:
        as_of = _date(as_of, "as_of")
    else:
        as_of = datetime.date.today().isoformat()
    posted = []
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT * FROM recurring_expenses
               WHERE business_id = ? AND active = 1 AND next_date <= ?
               AND (end_date IS NULL OR end_date >= next_date)""",
            (business_id, as_of),
        ).fetchall()
        for row in rows:
            expense_data = {
                "business_id": business_id,
                "vendor_id": row["vendor_id"],
                "expense_date": row["next_date"],
                "reference": f"RECUR-{row['id']}",
                "description": row["description"],
                "amount": row["amount"],
                "expense_account_id": row["expense_account_id"],
                "payment_account_id": row["payment_account_id"],
            }
            create_expense(expense_data)
            next_date = _advance_date(row["next_date"], row["frequency"])
            if row["end_date"] and next_date > row["end_date"]:
                conn.execute("UPDATE recurring_expenses SET active = 0, last_posted_date = ?, next_date = ?, updated_at = ? WHERE id = ?",
                             (row["next_date"], next_date, now_utc(), row["id"]))
            else:
                conn.execute("UPDATE recurring_expenses SET last_posted_date = ?, next_date = ?, updated_at = ? WHERE id = ?",
                             (row["next_date"], next_date, now_utc(), row["id"]))
            posted.append(row_to_dict(row))
        conn.commit()
    return posted


def list_closing_periods(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            "SELECT * FROM closing_periods WHERE business_id = ? ORDER BY period_end DESC",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def _is_period_closed(conn, business_id: int, entry_date: str) -> bool:
    row = conn.execute(
        "SELECT id FROM closing_periods WHERE business_id = ? AND ? >= period_start AND ? <= period_end",
        (business_id, entry_date, entry_date),
    ).fetchone()
    return row is not None


def close_period(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    period_start = _date(data.get("period_start"), "period_start")
    period_end = _date(data.get("period_end"), "period_end")
    if period_end < period_start:
        raise ValueError("period_end cannot be before period_start")
    notes = str(data.get("notes", "")).strip()
    closed_by = str(data.get("closed_by", "")).strip()
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        # Check for overlapping closed periods
        overlap = conn.execute(
            "SELECT id FROM closing_periods WHERE business_id = ? AND (? < period_end AND ? > period_start)",
            (business_id, period_start, period_end),
        ).fetchone()
        if overlap:
            raise ValueError("Period overlaps with an existing closed period")
        try:
            cursor = conn.execute(
                "INSERT INTO closing_periods (business_id, period_start, period_end, closed_by, closed_at, notes) VALUES (?, ?, ?, ?, ?, ?)",
                (business_id, period_start, period_end, closed_by, now, notes),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Period already closed")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM closing_periods WHERE id = ?", (cursor.lastrowid,)).fetchone())


def reopen_period(period_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM closing_periods WHERE id = ?", (period_id,)).fetchone()
        if row is None:
            raise ValueError("Closing period not found")
        conn.execute("DELETE FROM closing_periods WHERE id = ?", (period_id,))
        conn.commit()


def is_period_closed(business_id: int, entry_date: str) -> dict[str, Any]:
    entry_date = _date(entry_date, "entry_date")
    with get_db() as conn:
        _require_business(conn, business_id)
        return {"entry_date": entry_date, "closed": _is_period_closed(conn, business_id, entry_date)}


def customer_statement(business_id: int, customer_id: int, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """Generate a customer statement with invoices, payments, and balance."""
    with get_db() as conn:
        _require_business(conn, business_id)
        contact = conn.execute("SELECT * FROM accounting_contacts WHERE id = ? AND business_id = ? AND contact_type IN ('customer', 'both')", (customer_id, business_id)).fetchone()
        if contact is None:
            raise ValueError("Customer not found for this business")
        query = "SELECT * FROM invoices WHERE business_id = ? AND customer_id = ?"
        params: list[Any] = [business_id, customer_id]
        if start_date:
            query += " AND issue_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND issue_date <= ?"
            params.append(end_date)
        query += " ORDER BY issue_date, id"
        invoices = [row_to_dict(r) for r in conn.execute(query, params).fetchall()]
        invoice_ids = [inv["id"] for inv in invoices]
        payments: list[dict[str, Any]] = []
        if invoice_ids:
            placeholders = ",".join("?" * len(invoice_ids))
            pay_rows = conn.execute(f"SELECT * FROM invoice_payments WHERE invoice_id IN ({placeholders}) ORDER BY payment_date", invoice_ids).fetchall()
            payments = [row_to_dict(r) for r in pay_rows]
        total_invoiced = round(sum(inv["amount"] for inv in invoices), 2)
        total_paid = round(sum(p["amount"] for p in payments), 2)
        balance_due = round(total_invoiced - total_paid, 2)
        return {
            "customer": row_to_dict(contact),
            "invoices": invoices,
            "payments": payments,
            "total_invoiced": total_invoiced,
            "total_paid": total_paid,
            "balance_due": balance_due,
        }


def vendor_statement(business_id: int, vendor_id: int, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """Generate a vendor statement with expenses and total spent."""
    with get_db() as conn:
        _require_business(conn, business_id)
        contact = conn.execute("SELECT * FROM accounting_contacts WHERE id = ? AND business_id = ? AND contact_type IN ('vendor', 'both')", (vendor_id, business_id)).fetchone()
        if contact is None:
            raise ValueError("Vendor not found for this business")
        query = "SELECT * FROM expenses WHERE business_id = ? AND vendor_id = ?"
        params: list[Any] = [business_id, vendor_id]
        if start_date:
            query += " AND expense_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND expense_date <= ?"
            params.append(end_date)
        query += " ORDER BY expense_date, id"
        expenses = [row_to_dict(r) for r in conn.execute(query, params).fetchall()]
        total_spent = round(sum(exp["amount"] for exp in expenses), 2)
        return {
            "vendor": row_to_dict(contact),
            "expenses": expenses,
            "total_spent": total_spent,
            "expense_count": len(expenses),
        }


def list_account_groups(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT ag.*, COUNT(a.id) AS account_count
               FROM account_groups ag
               LEFT JOIN accounts a ON a.group_id = ag.id AND a.business_id = ag.business_id
               WHERE ag.business_id = ?
               GROUP BY ag.id
               ORDER BY ag.account_type, ag.display_order, ag.name""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_account_group(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    account_type = str(data.get("account_type", "")).strip().lower()
    if account_type not in ACCOUNT_TYPES:
        raise ValueError(f"account_type must be one of: {', '.join(sorted(ACCOUNT_TYPES))}")
    display_order = int(data.get("display_order", 0))
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        try:
            cursor = conn.execute(
                "INSERT INTO account_groups (business_id, name, account_type, display_order, created_at) VALUES (?, ?, ?, ?, ?)",
                (business_id, name, account_type, display_order, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Account group with this name already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM account_groups WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_account_group(group_id: int, data: dict[str, Any]) -> dict[str, Any]:
    name = str(data.get("name", "")).strip()
    display_order = data.get("display_order")
    account_type = str(data.get("account_type", "")).strip().lower()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM account_groups WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            raise ValueError("Account group not found")
        updates: list[str] = []
        params: list[Any] = []
        if name:
            updates.append("name = ?")
            params.append(name)
        if display_order is not None:
            updates.append("display_order = ?")
            params.append(int(display_order))
        if account_type:
            if account_type not in ACCOUNT_TYPES:
                raise ValueError(f"account_type must be one of: {', '.join(sorted(ACCOUNT_TYPES))}")
            updates.append("account_type = ?")
            params.append(account_type)
        if updates:
            updates.append("created_at = created_at")
            conn.execute(f"UPDATE account_groups SET {', '.join(updates)} WHERE id = ?", [*params, group_id])
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM account_groups WHERE id = ?", (group_id,)).fetchone())


def delete_account_group(group_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM account_groups WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            raise ValueError("Account group not found")
        # Unlink accounts from this group before deleting
        conn.execute("UPDATE accounts SET group_id = NULL WHERE group_id = ?", (group_id,))
        conn.execute("DELETE FROM account_groups WHERE id = ?", (group_id,))
        conn.commit()


def assign_account_to_group(account_id: int, group_id: int) -> dict[str, Any]:
    with get_db() as conn:
        account = conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if account is None:
            raise ValueError("Account not found")
        group = conn.execute("SELECT * FROM account_groups WHERE id = ?", (group_id,)).fetchone()
        if group is None:
            raise ValueError("Account group not found")
        if group["business_id"] != account["business_id"]:
            raise ValueError("Account and group must belong to the same business")
        if group["account_type"] != account["account_type"]:
            raise ValueError("Account type must match group type")
        conn.execute("UPDATE accounts SET group_id = ?, updated_at = ? WHERE id = ?", (group_id, now_utc(), account_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone())


def list_payment_terms(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            "SELECT * FROM payment_terms WHERE business_id = ? ORDER BY is_default DESC, net_days",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_payment_terms(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    net_days = int(data.get("net_days", 30))
    if net_days < 0:
        raise ValueError("net_days must be >= 0")
    discount_percent = float(data.get("discount_percent", 0))
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("discount_percent must be between 0 and 100")
    discount_days = int(data.get("discount_days", 0))
    if discount_days < 0:
        raise ValueError("discount_days must be >= 0")
    description = str(data.get("description", "")).strip()
    is_default = 1 if data.get("is_default") else 0
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if is_default:
            existing_default = conn.execute("SELECT id FROM payment_terms WHERE business_id = ? AND is_default = 1", (business_id,)).fetchone()
            if existing_default:
                raise ValueError("Business already has a default payment term")
        try:
            cursor = conn.execute(
                "INSERT INTO payment_terms (business_id, name, net_days, discount_percent, discount_days, description, is_default, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (business_id, name, net_days, discount_percent, discount_days, description, is_default, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Payment term with this name already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM payment_terms WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_payment_terms(term_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM payment_terms WHERE id = ?", (term_id,)).fetchone()
        if row is None:
            raise ValueError("Payment term not found")
        updates: list[str] = []
        params: list[Any] = []
        for field in ("name", "description"):
            val = data.get(field)
            if val is not None:
                updates.append(f"{field} = ?")
                params.append(str(val).strip())
        for field in ("net_days", "discount_days"):
            val = data.get(field)
            if val is not None:
                val = int(val)
                if val < 0:
                    raise ValueError(f"{field} must be >= 0")
                updates.append(f"{field} = ?")
                params.append(val)
        if "discount_percent" in data:
            val = float(data["discount_percent"])
            if val < 0 or val > 100:
                raise ValueError("discount_percent must be between 0 and 100")
            updates.append("discount_percent = ?")
            params.append(val)
        if "is_default" in data:
            is_default = 1 if data["is_default"] else 0
            if is_default and not row["is_default"]:
                existing = conn.execute("SELECT id FROM payment_terms WHERE business_id = ? AND is_default = 1 AND id != ?", (row["business_id"], term_id)).fetchone()
                if existing:
                    raise ValueError("Business already has a default payment term")
            updates.append("is_default = ?")
            params.append(is_default)
        if updates:
            updates.append("updated_at = ?")
            params.append(now_utc())
            conn.execute(f"UPDATE payment_terms SET {', '.join(updates)} WHERE id = ?", [*params, term_id])
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM payment_terms WHERE id = ?", (term_id,)).fetchone())


def delete_payment_terms(term_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM payment_terms WHERE id = ?", (term_id,)).fetchone()
        if row is None:
            raise ValueError("Payment term not found")
        conn.execute("DELETE FROM payment_terms WHERE id = ?", (term_id,))
        conn.commit()


def calculate_due_date(issue_date: str, net_days: int) -> str:
    """Calculate due date from issue date and net days."""
    import datetime
    d = datetime.date.fromisoformat(issue_date)
    due = d + datetime.timedelta(days=net_days)
    return due.isoformat()


def list_credit_notes(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT cn.*, c.name AS customer_name, i.invoice_number AS invoice_number
               FROM credit_notes cn
               LEFT JOIN accounting_contacts c ON c.id = cn.customer_id
               LEFT JOIN invoices i ON i.id = cn.invoice_id
               WHERE cn.business_id = ?
               ORDER BY cn.credit_date DESC, cn.id DESC""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def get_credit_note_detail(business_id: int, credit_id: int) -> dict[str, Any]:
    with get_db() as conn:
        _require_business(conn, business_id)
        row = conn.execute(
            """SELECT cn.*, c.name AS customer_name, i.invoice_number AS invoice_number
               FROM credit_notes cn
               LEFT JOIN accounting_contacts c ON c.id = cn.customer_id
               LEFT JOIN invoices i ON i.id = cn.invoice_id
               WHERE cn.business_id = ? AND cn.id = ?""",
            (business_id, credit_id),
        ).fetchone()
        if row is None:
            raise ValueError("Credit note not found")
        return row_to_dict(row)


def create_credit_note(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    credit_number = str(data.get("credit_number", "")).strip()
    if not credit_number:
        raise ValueError("credit_number is required")
    credit_date = _date(data.get("credit_date"), "credit_date")
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        raise ValueError("amount must be a number")
    if amount <= 0:
        raise ValueError("amount must be positive")
    reason = str(data.get("reason", "")).strip()
    invoice_id = data.get("invoice_id")
    customer_id = data.get("customer_id")
    receivable_account_id = data.get("receivable_account_id")
    revenue_account_id = data.get("revenue_account_id")
    if receivable_account_id is None or revenue_account_id is None:
        raise ValueError("receivable_account_id and revenue_account_id are required")
    receivable_account_id = int(receivable_account_id)
    revenue_account_id = int(revenue_account_id)
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if _is_period_closed(conn, business_id, credit_date):
            raise ValueError("Cannot post to a closed accounting period")
        # Validate accounts
        for aid in (receivable_account_id, revenue_account_id):
            acct = conn.execute("SELECT * FROM accounts WHERE id = ? AND business_id = ?", (aid, business_id)).fetchone()
            if acct is None:
                raise ValueError("Account not found for this business")
        # Validate invoice if provided
        if invoice_id is not None:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ? AND business_id = ?", (invoice_id, business_id)).fetchone()
            if inv is None:
                raise ValueError("Invoice not found for this business")
            if customer_id is None:
                customer_id = inv["customer_id"]
        # Validate customer if provided
        if customer_id is not None:
            cust = conn.execute("SELECT * FROM accounting_contacts WHERE id = ? AND business_id = ?", (customer_id, business_id)).fetchone()
            if cust is None:
                raise ValueError("Customer not found for this business")
        # Create reversing journal entry: credit receivable (reduce AR), debit revenue (reduce revenue)
        entry_cursor = conn.execute(
            "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'posted', ?, ?)",
            (business_id, credit_date, credit_number, f"Credit note {credit_number}", now, now),
        )
        entry_id = entry_cursor.lastrowid
        # Debit revenue (reduce revenue), credit receivable (reduce AR)
        conn.execute(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
            (entry_id, revenue_account_id, f"Credit note {credit_number}", amount, 0),
        )
        conn.execute(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
            (entry_id, receivable_account_id, f"Credit note {credit_number}", 0, amount),
        )
        # If linked to invoice, reduce invoice amount
        if invoice_id is not None:
            conn.execute("UPDATE invoices SET amount_paid = amount_paid + ?, updated_at = ? WHERE id = ?",
                         (amount, now, invoice_id))
        try:
            cursor = conn.execute(
                "INSERT INTO credit_notes (business_id, invoice_id, customer_id, credit_number, credit_date, amount, reason, receivable_account_id, revenue_account_id, journal_entry_id, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'applied', ?, ?)",
                (business_id, invoice_id, customer_id, credit_number, credit_date, amount, reason, receivable_account_id, revenue_account_id, entry_id, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Credit note number already exists for this business")
        conn.commit()
        return get_credit_note_detail(business_id, cursor.lastrowid)


def void_credit_note(business_id: int, credit_id: int) -> dict[str, Any]:
    with get_db() as conn:
        _require_business(conn, business_id)
        row = conn.execute("SELECT * FROM credit_notes WHERE id = ? AND business_id = ?", (credit_id, business_id)).fetchone()
        if row is None:
            raise ValueError("Credit note not found")
        if row["status"] == "void":
            raise ValueError("Credit note is already void")
        # Create reversing entry
        now = now_utc()
        entry_cursor = conn.execute(
            "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'posted', ?, ?)",
            (business_id, now[:10], f"VOID-{row['credit_number']}", f"Void credit note {row['credit_number']}", now, now),
        )
        entry_id = entry_cursor.lastrowid
        # Reverse the original entry
        conn.execute(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
            (entry_id, row["receivable_account_id"], f"Void CN {row['credit_number']}", row["amount"], 0),
        )
        conn.execute(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
            (entry_id, row["revenue_account_id"], f"Void CN {row['credit_number']}", 0, row["amount"]),
        )
        # If linked to invoice, reverse the amount_paid reduction
        if row["invoice_id"] is not None:
            conn.execute("UPDATE invoices SET amount_paid = MAX(amount_paid - ?, 0), updated_at = ? WHERE id = ?",
                         (row["amount"], now, row["invoice_id"]))
        conn.execute("UPDATE credit_notes SET status = 'void', updated_at = ? WHERE id = ?", (now, credit_id))
        conn.commit()
        return get_credit_note_detail(business_id, credit_id)


def list_depreciation_assets(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT da.*, a.code AS asset_code, aa.code AS accumulated_code, dp.code AS depreciation_code
               FROM depreciation_assets da
               LEFT JOIN accounts a ON a.id = da.asset_account_id
               LEFT JOIN accounts aa ON aa.id = da.accumulated_account_id
               LEFT JOIN accounts dp ON dp.id = da.depreciation_account_id
               WHERE da.business_id = ? ORDER BY da.acquisition_date DESC""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_depreciation_asset(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    try:
        asset_account_id = int(data.get("asset_account_id"))
        accumulated_account_id = int(data.get("accumulated_account_id"))
        depreciation_account_id = int(data.get("depreciation_account_id"))
    except (TypeError, ValueError):
        raise ValueError("asset_account_id, accumulated_account_id, and depreciation_account_id are required")
    try:
        cost = float(data.get("cost", 0))
    except (TypeError, ValueError):
        raise ValueError("cost must be a number")
    if cost <= 0:
        raise ValueError("cost must be positive")
    salvage_value = float(data.get("salvage_value", 0))
    if salvage_value < 0:
        raise ValueError("salvage_value must be >= 0")
    useful_life_months = int(data.get("useful_life_months", 0))
    if useful_life_months <= 0:
        raise ValueError("useful_life_months must be > 0")
    method = str(data.get("method", "straight_line")).strip().lower()
    if method not in ("straight_line", "declining_balance"):
        raise ValueError("method must be 'straight_line' or 'declining_balance'")
    depreciation_rate = float(data.get("depreciation_rate", 0))
    if depreciation_rate < 0 or depreciation_rate > 100:
        raise ValueError("depreciation_rate must be between 0 and 100")
    if method == "declining_balance" and depreciation_rate <= 0:
        raise ValueError("depreciation_rate is required for declining_balance method")
    acquisition_date = _date(data.get("acquisition_date"), "acquisition_date")
    start_date = _date(data.get("start_date", acquisition_date), "start_date")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        for aid in (asset_account_id, accumulated_account_id, depreciation_account_id):
            acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (aid, business_id)).fetchone()
            if acct is None:
                raise ValueError("Account not found for this business")
        cursor = conn.execute(
            "INSERT INTO depreciation_assets (business_id, name, asset_account_id, accumulated_account_id, depreciation_account_id, cost, salvage_value, useful_life_months, method, depreciation_rate, acquisition_date, start_date, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (business_id, name, asset_account_id, accumulated_account_id, depreciation_account_id, cost, salvage_value, useful_life_months, method, depreciation_rate, acquisition_date, start_date, now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (cursor.lastrowid,)).fetchone())


def depreciation_schedule(asset_id: int) -> dict[str, Any]:
    """Calculate the depreciation schedule for an asset."""
    import datetime
    with get_db() as conn:
        asset = conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (asset_id,)).fetchone()
        if asset is None:
            raise ValueError("Depreciation asset not found")
        asset = row_to_dict(asset)
        depreciable_base = asset["cost"] - asset["salvage_value"]
        schedule: list[dict[str, Any]] = []
        if asset["method"] == "straight_line":
            monthly_depreciation = round(depreciable_base / asset["useful_life_months"], 2)
            start = datetime.date.fromisoformat(asset["start_date"])
            accumulated = 0.0
            for month in range(asset["useful_life_months"]):
                month_date = start
                for _ in range(month):
                    if month_date.month == 12:
                        month_date = month_date.replace(year=month_date.year + 1, month=1)
                    else:
                        month_date = month_date.replace(month=month_date.month + 1)
                # Adjust for rounding on last period
                if month == asset["useful_life_months"] - 1:
                    dep_amount = round(depreciable_base - accumulated, 2)
                else:
                    dep_amount = monthly_depreciation
                accumulated = round(accumulated + dep_amount, 2)
                schedule.append({
                    "period": month + 1,
                    "date": month_date.isoformat(),
                    "depreciation": dep_amount,
                    "accumulated": accumulated,
                    "book_value": round(asset["cost"] - accumulated, 2),
                })
        else:  # declining_balance
            rate = asset["depreciation_rate"] / 100
            start = datetime.date.fromisoformat(asset["start_date"])
            book_value = asset["cost"]
            accumulated = 0.0
            for month in range(asset["useful_life_months"]):
                month_date = start
                for _ in range(month):
                    if month_date.month == 12:
                        month_date = month_date.replace(year=month_date.year + 1, month=1)
                    else:
                        month_date = month_date.replace(month=month_date.month + 1)
                dep_amount = round(book_value * rate / 12, 2)
                # Don't depreciate below salvage value
                if book_value - dep_amount < asset["salvage_value"]:
                    dep_amount = round(book_value - asset["salvage_value"], 2)
                if dep_amount <= 0:
                    break
                book_value = round(book_value - dep_amount, 2)
                accumulated = round(accumulated + dep_amount, 2)
                schedule.append({
                    "period": month + 1,
                    "date": month_date.isoformat(),
                    "depreciation": dep_amount,
                    "accumulated": accumulated,
                    "book_value": book_value,
                })
        return {
            "asset": asset,
            "schedule": schedule,
            "total_depreciation": schedule[-1]["accumulated"] if schedule else 0,
            "final_book_value": schedule[-1]["book_value"] if schedule else asset["cost"],
        }


def post_depreciation(asset_id: int, through_date: str) -> dict[str, Any]:
    """Post a depreciation journal entry for an asset up to the given date."""
    import datetime
    through_date = _date(through_date, "through_date")
    with get_db() as conn:
        asset = conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (asset_id,)).fetchone()
        if asset is None:
            raise ValueError("Depreciation asset not found")
        asset = row_to_dict(asset)
        if asset["status"] != "active":
            raise ValueError("Asset is not active")
        if _is_period_closed(conn, asset["business_id"], through_date):
            raise ValueError("Cannot post to a closed accounting period")
        # Calculate depreciation amount up to through_date
        schedule = depreciation_schedule(asset_id)
        total_dep = 0.0
        for entry in schedule["schedule"]:
            if entry["date"] <= through_date:
                total_dep = entry["accumulated"]
            else:
                break
        if total_dep <= 0:
            raise ValueError("No depreciation to post for this period")
        now = now_utc()
        # Create journal entry: debit depreciation expense, credit accumulated depreciation
        entry_cursor = conn.execute(
            "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'posted', ?, ?)",
            (asset["business_id"], through_date, f"DEP-{asset['id']}", f"Depreciation for {asset['name']}", now, now),
        )
        entry_id = entry_cursor.lastrowid
        conn.execute(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
            (entry_id, asset["depreciation_account_id"], f"Depreciation {asset['name']}", total_dep, 0),
        )
        conn.execute(
            "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
            (entry_id, asset["accumulated_account_id"], f"Accumulated dep {asset['name']}", 0, total_dep),
        )
        # Check if fully depreciated
        if total_dep >= (asset["cost"] - asset["salvage_value"]):
            conn.execute("UPDATE depreciation_assets SET status = 'fully_depreciated', updated_at = ? WHERE id = ?", (now, asset_id))
        conn.commit()
        return {"posted": True, "amount": total_dep, "entry_id": entry_id}


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


def list_projects(business_id: int, status: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = """SELECT p.*, c.name AS customer_name, cc.code AS cost_center_code
                  FROM projects p
                  LEFT JOIN accounting_contacts c ON c.id = p.customer_id
                  LEFT JOIN cost_centers cc ON cc.id = p.cost_center_id
                  WHERE p.business_id = ?"""
        params: list[Any] = [business_id]
        if status:
            query += " AND p.status = ?"
            params.append(status)
        query += " ORDER BY p.start_date DESC, p.id DESC"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_project(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    if not code or not name:
        raise ValueError("code and name are required")
    description = str(data.get("description", "")).strip()
    customer_id = data.get("customer_id")
    start_date = _date(data.get("start_date"), "start_date")
    end_date = data.get("end_date")
    if end_date:
        end_date = _date(end_date, "end_date")
        if end_date < start_date:
            raise ValueError("end_date cannot be before start_date")
    budgeted_revenue = float(data.get("budgeted_revenue", 0))
    budgeted_cost = float(data.get("budgeted_cost", 0))
    if budgeted_revenue < 0 or budgeted_cost < 0:
        raise ValueError("budgeted_revenue and budgeted_cost must be >= 0")
    status = str(data.get("status", "active")).strip().lower()
    if status not in ("active", "completed", "on_hold", "cancelled"):
        raise ValueError("status must be one of: active, completed, on_hold, cancelled")
    cost_center_id = data.get("cost_center_id")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if customer_id is not None:
            cust = conn.execute("SELECT id FROM accounting_contacts WHERE id = ? AND business_id = ?", (customer_id, business_id)).fetchone()
            if cust is None:
                raise ValueError("Customer not found for this business")
        if cost_center_id is not None:
            cc = conn.execute("SELECT id FROM cost_centers WHERE id = ? AND business_id = ?", (cost_center_id, business_id)).fetchone()
            if cc is None:
                raise ValueError("Cost center not found for this business")
        try:
            cursor = conn.execute(
                "INSERT INTO projects (business_id, code, name, description, customer_id, start_date, end_date, budgeted_revenue, budgeted_cost, status, cost_center_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (business_id, code, name, description, customer_id, start_date, end_date, budgeted_revenue, budgeted_cost, status, cost_center_id, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Project code already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_project(project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ValueError("Project not found")
        updates: list[str] = []
        params: list[Any] = []
        for field in ("name", "description"):
            val = data.get(field)
            if val is not None:
                updates.append(f"{field} = ?")
                params.append(str(val).strip())
        for field in ("budgeted_revenue", "budgeted_cost"):
            val = data.get(field)
            if val is not None:
                val = float(val)
                if val < 0:
                    raise ValueError(f"{field} must be >= 0")
                updates.append(f"{field} = ?")
                params.append(val)
        if "end_date" in data:
            val = data.get("end_date")
            if val:
                val = _date(val, "end_date")
            updates.append("end_date = ?")
            params.append(val)
        if "status" in data:
            status = str(data["status"]).strip().lower()
            if status not in ("active", "completed", "on_hold", "cancelled"):
                raise ValueError("status must be one of: active, completed, on_hold, cancelled")
            updates.append("status = ?")
            params.append(status)
        if "customer_id" in data:
            updates.append("customer_id = ?")
            params.append(data["customer_id"])
        if updates:
            updates.append("updated_at = ?")
            params.append(now_utc())
            conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", [*params, project_id])
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())


def delete_project(project_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ValueError("Project not found")
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()


def project_profitability(project_id: int) -> dict[str, Any]:
    """Calculate actual revenue and expenses for a project via its cost center."""
    with get_db() as conn:
        project = conn.execute(
            """SELECT p.*, c.name AS customer_name, cc.code AS cost_center_code
               FROM projects p
               LEFT JOIN accounting_contacts c ON c.id = p.customer_id
               LEFT JOIN cost_centers cc ON cc.id = p.cost_center_id
               WHERE p.id = ?""",
            (project_id,),
        ).fetchone()
        if project is None:
            raise ValueError("Project not found")
        project = row_to_dict(project)
        actual_revenue = 0.0
        actual_cost = 0.0
        if project["cost_center_id"]:
            # Get revenue entries linked to this cost center
            rev_rows = conn.execute(
                """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS total
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   JOIN accounts a ON a.id = jl.account_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND jl.cost_center_id = ? AND a.account_type = 'revenue'""",
                (project["business_id"], project["cost_center_id"]),
            ).fetchone()
            actual_revenue = round(rev_rows["total"], 2)
            # Get expense entries linked to this cost center
            exp_rows = conn.execute(
                """SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS total
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   JOIN accounts a ON a.id = jl.account_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND jl.cost_center_id = ? AND a.account_type = 'expense'""",
                (project["business_id"], project["cost_center_id"]),
            ).fetchone()
            actual_cost = round(exp_rows["total"], 2)
        actual_profit = round(actual_revenue - actual_cost, 2)
        budgeted_profit = round(project["budgeted_revenue"] - project["budgeted_cost"], 2)
        return {
            "project": project,
            "budgeted_revenue": project["budgeted_revenue"],
            "budgeted_cost": project["budgeted_cost"],
            "budgeted_profit": budgeted_profit,
            "actual_revenue": actual_revenue,
            "actual_cost": actual_cost,
            "actual_profit": actual_profit,
            "revenue_variance": round(actual_revenue - project["budgeted_revenue"], 2),
            "cost_variance": round(actual_cost - project["budgeted_cost"], 2),
            "profit_variance": round(actual_profit - budgeted_profit, 2),
            "profit_margin": round((actual_profit / actual_revenue) * 100, 2) if actual_revenue > 0 else None,
        }


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


def list_bank_transactions(business_id: int, account_id: int | None = None, cleared: bool | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = "SELECT * FROM bank_transactions WHERE business_id = ?"
        params: list[Any] = [business_id]
        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        if cleared is not None:
            query += " AND cleared = ?"
            params.append(1 if cleared else 0)
        query += " ORDER BY transaction_date DESC, id DESC"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_bank_transaction(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    try:
        account_id = int(data.get("account_id"))
    except (TypeError, ValueError):
        raise ValueError("account_id is required")
    transaction_date = _date(data.get("transaction_date"), "transaction_date")
    description = str(data.get("description", "")).strip()
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        raise ValueError("amount must be a number")
    if amount <= 0:
        raise ValueError("amount must be positive")
    tx_type = str(data.get("type", "")).strip().lower()
    if tx_type not in ("deposit", "withdrawal", "fee", "interest"):
        raise ValueError("type must be one of: deposit, withdrawal, fee, interest")
    reference = str(data.get("reference", "")).strip()
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (account_id, business_id)).fetchone()
        if acct is None:
            raise ValueError("Account not found for this business")
        cursor = conn.execute(
            "INSERT INTO bank_transactions (business_id, account_id, transaction_date, description, amount, type, reference, cleared, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (business_id, account_id, transaction_date, description, amount, tx_type, reference, now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (cursor.lastrowid,)).fetchone())


def match_bank_transaction(transaction_id: int, journal_line_id: int) -> dict[str, Any]:
    with get_db() as conn:
        tx = conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone()
        if tx is None:
            raise ValueError("Bank transaction not found")
        tx = row_to_dict(tx)
        jl = conn.execute("SELECT * FROM journal_lines WHERE id = ?", (journal_line_id,)).fetchone()
        if jl is None:
            raise ValueError("Journal line not found")
        # Verify the journal line belongs to the same business
        je = conn.execute("SELECT business_id FROM journal_entries WHERE id = ?", (jl["entry_id"],)).fetchone()
        if je is None or je["business_id"] != tx["business_id"]:
            raise ValueError("Journal line does not belong to the same business")
        now = now_utc()
        conn.execute("UPDATE bank_transactions SET matched_journal_line_id = ?, cleared = 1, updated_at = ? WHERE id = ?", (journal_line_id, now, transaction_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone())


def unmatch_bank_transaction(transaction_id: int) -> dict[str, Any]:
    with get_db() as conn:
        tx = conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone()
        if tx is None:
            raise ValueError("Bank transaction not found")
        now = now_utc()
        conn.execute("UPDATE bank_transactions SET matched_journal_line_id = NULL, cleared = 0, updated_at = ? WHERE id = ?", (now, transaction_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone())


def delete_bank_transaction(transaction_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone() is None:
            raise ValueError("Bank transaction not found")
        conn.execute("DELETE FROM bank_transactions WHERE id = ?", (transaction_id,))
        conn.commit()


def bank_reconciliation_summary(business_id: int, account_id: int) -> dict[str, Any]:
    with get_db() as conn:
        _require_business(conn, business_id)
        acct = conn.execute("SELECT * FROM accounts WHERE id = ? AND business_id = ?", (account_id, business_id)).fetchone()
        if acct is None:
            raise ValueError("Account not found for this business")
        acct = row_to_dict(acct)
        txs = conn.execute("SELECT * FROM bank_transactions WHERE business_id = ? AND account_id = ?", (business_id, account_id)).fetchall()
        txs = [row_to_dict(t) for t in txs]
        cleared = [t for t in txs if t["cleared"]]
        uncleared = [t for t in txs if not t["cleared"]]
        cleared_total = round(sum(t["amount"] if t["type"] in ("deposit", "interest") else -t["amount"] for t in cleared), 2)
        uncleared_total = round(sum(t["amount"] if t["type"] in ("deposit", "interest") else -t["amount"] for t in uncleared), 2)
        # Get book balance from posted entries
        balances = _account_balances(conn, business_id, datetime.date.today().isoformat())
        acct_balance = next((row for row in balances if row["id"] == account_id), None)
        if acct_balance is None:
            book_balance = 0.0
        elif acct["account_type"] in ("asset", "expense"):
            book_balance = round(acct_balance["debits"] - acct_balance["credits"], 2)
        else:
            book_balance = round(acct_balance["credits"] - acct_balance["debits"], 2)
        return {
            "account": acct,
            "total_transactions": len(txs),
            "cleared_count": len(cleared),
            "uncleared_count": len(uncleared),
            "cleared_total": cleared_total,
            "uncleared_total": uncleared_total,
            "book_balance": book_balance,
            "difference": round(book_balance - cleared_total, 2),
            "cleared_transactions": cleared,
            "uncleared_transactions": uncleared,
        }


def list_sales_tax_rates(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            "SELECT * FROM sales_tax_rates WHERE business_id = ? ORDER BY is_default DESC, name",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_sales_tax_rate(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    rate = float(data.get("rate", 0))
    if rate < 0 or rate > 100:
        raise ValueError("rate must be between 0 and 100")
    tax_account_id = data.get("tax_account_id")
    is_default = 1 if data.get("is_default") else 0
    active = 1 if data.get("active", True) else 0
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if tax_account_id is not None:
            acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (tax_account_id, business_id)).fetchone()
            if acct is None:
                raise ValueError("Account not found for this business")
        if is_default:
            existing = conn.execute("SELECT id FROM sales_tax_rates WHERE business_id = ? AND is_default = 1", (business_id,)).fetchone()
            if existing:
                raise ValueError("Business already has a default tax rate")
        try:
            cursor = conn.execute(
                "INSERT INTO sales_tax_rates (business_id, name, rate, tax_account_id, is_default, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (business_id, name, rate, tax_account_id, is_default, active, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Tax rate with this name already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM sales_tax_rates WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_sales_tax_rate(rate_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sales_tax_rates WHERE id = ?", (rate_id,)).fetchone()
        if row is None:
            raise ValueError("Tax rate not found")
        updates: list[str] = []
        params: list[Any] = []
        if "name" in data:
            updates.append("name = ?")
            params.append(str(data["name"]).strip())
        if "rate" in data:
            rate = float(data["rate"])
            if rate < 0 or rate > 100:
                raise ValueError("rate must be between 0 and 100")
            updates.append("rate = ?")
            params.append(rate)
        if "active" in data:
            updates.append("active = ?")
            params.append(1 if data["active"] else 0)
        if "is_default" in data:
            is_default = 1 if data["is_default"] else 0
            if is_default and not row["is_default"]:
                existing = conn.execute("SELECT id FROM sales_tax_rates WHERE business_id = ? AND is_default = 1 AND id != ?", (row["business_id"], rate_id)).fetchone()
                if existing:
                    raise ValueError("Business already has a default tax rate")
            updates.append("is_default = ?")
            params.append(is_default)
        if updates:
            updates.append("updated_at = ?")
            params.append(now_utc())
            conn.execute(f"UPDATE sales_tax_rates SET {', '.join(updates)} WHERE id = ?", [*params, rate_id])
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM sales_tax_rates WHERE id = ?", (rate_id,)).fetchone())


def delete_sales_tax_rate(rate_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM sales_tax_rates WHERE id = ?", (rate_id,)).fetchone() is None:
            raise ValueError("Tax rate not found")
        conn.execute("DELETE FROM sales_tax_rates WHERE id = ?", (rate_id,))
        conn.commit()


def calculate_sales_tax(amount: float, rate: float) -> dict[str, Any]:
    if amount < 0:
        raise ValueError("amount must be >= 0")
    if rate < 0 or rate > 100:
        raise ValueError("rate must be between 0 and 100")
    tax_amount = round(amount * rate / 100, 2)
    total = round(amount + tax_amount, 2)
    return {"amount": amount, "rate": rate, "tax_amount": tax_amount, "total": total}


def sales_tax_summary(business_id: int, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
    """Summarize sales tax collected from invoices in a date range."""
    with get_db() as conn:
        _require_business(conn, business_id)
        query = "SELECT amount, amount_paid, issue_date FROM invoices WHERE business_id = ? AND status != 'void'"
        params: list[Any] = [business_id]
        if start_date:
            query += " AND issue_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND issue_date <= ?"
            params.append(end_date)
        rows = conn.execute(query, params).fetchall()
        rates = conn.execute("SELECT * FROM sales_tax_rates WHERE business_id = ? AND active = 1", (business_id,)).fetchall()
        rates = [row_to_dict(r) for r in rates]
        default_rate = next((r for r in rates if r["is_default"]), None)
        default_rate_value = default_rate["rate"] if default_rate else 0
        total_sales = round(sum(row["amount"] for row in rows), 2)
        total_collected = round(sum(row["amount"] * default_rate_value / 100 for row in rows), 2) if default_rate_value > 0 else 0.0
        return {
            "total_sales": total_sales,
            "default_rate": default_rate_value,
            "total_tax_collected": total_collected,
            "rate_count": len(rates),
            "rates": rates,
            "invoice_count": len(rows),
        }


def list_purchase_orders(business_id: int, status: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = """SELECT po.*, c.name AS vendor_name
                  FROM purchase_orders po
                  LEFT JOIN accounting_contacts c ON c.id = po.vendor_id
                  WHERE po.business_id = ?"""
        params: list[Any] = [business_id]
        if status:
            query += " AND po.status = ?"
            params.append(status)
        query += " ORDER BY po.order_date DESC, po.id DESC"
        orders = [row_to_dict(row) for row in conn.execute(query, params).fetchall()]
        for order in orders:
            lines = conn.execute("SELECT * FROM purchase_order_lines WHERE po_id = ?", (order["id"],)).fetchall()
            order["lines"] = [row_to_dict(l) for l in lines]
        return orders


def create_purchase_order(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    po_number = str(data.get("po_number", "")).strip()
    if not po_number:
        raise ValueError("po_number is required")
    order_date = _date(data.get("order_date"), "order_date")
    expected_date = data.get("expected_date")
    if expected_date:
        expected_date = _date(expected_date, "expected_date")
    vendor_id = data.get("vendor_id")
    try:
        expense_account_id = int(data.get("expense_account_id"))
        payment_account_id = int(data.get("payment_account_id"))
    except (TypeError, ValueError):
        raise ValueError("expense_account_id and payment_account_id are required")
    notes = str(data.get("notes", "")).strip()
    status = str(data.get("status", "draft")).strip().lower()
    if status not in ("draft", "sent", "received", "cancelled"):
        raise ValueError("status must be one of: draft, sent, received, cancelled")
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise ValueError("At least one line is required")
    lines = []
    total = 0.0
    for raw in raw_lines:
        if not isinstance(raw, dict):
            raise ValueError("Each line must be an object")
        desc = str(raw.get("description", "")).strip()
        if not desc:
            raise ValueError("Line description is required")
        quantity = float(raw.get("quantity", 0))
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        unit_price = float(raw.get("unit_price", 0))
        if unit_price < 0:
            raise ValueError("unit_price must be >= 0")
        line_total = round(quantity * unit_price, 2)
        total = round(total + line_total, 2)
        lines.append((desc, quantity, unit_price, line_total))
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        for aid in (expense_account_id, payment_account_id):
            acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (aid, business_id)).fetchone()
            if acct is None:
                raise ValueError("Account not found for this business")
        if vendor_id is not None:
            vendor = conn.execute("SELECT id FROM accounting_contacts WHERE id = ? AND business_id = ?", (vendor_id, business_id)).fetchone()
            if vendor is None:
                raise ValueError("Vendor not found for this business")
        try:
            cursor = conn.execute(
                "INSERT INTO purchase_orders (business_id, po_number, order_date, expected_date, vendor_id, expense_account_id, payment_account_id, total_amount, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (business_id, po_number, order_date, expected_date, vendor_id, expense_account_id, payment_account_id, total, status, notes, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("PO number already exists for this business")
        po_id = cursor.lastrowid
        for line in lines:
            conn.execute("INSERT INTO purchase_order_lines (po_id, description, quantity, unit_price, line_total) VALUES (?, ?, ?, ?, ?)", (po_id, *line))
        conn.commit()
        return _get_purchase_order_detail(conn, po_id)


def _get_purchase_order_detail(conn, po_id: int) -> dict[str, Any]:
    order = row_to_dict(conn.execute(
        """SELECT po.*, c.name AS vendor_name FROM purchase_orders po
           LEFT JOIN accounting_contacts c ON c.id = po.vendor_id WHERE po.id = ?""",
        (po_id,),
    ).fetchone())
    lines = conn.execute("SELECT * FROM purchase_order_lines WHERE po_id = ?", (po_id,)).fetchall()
    order["lines"] = [row_to_dict(l) for l in lines]
    return order


def update_purchase_order_status(po_id: int, status: str) -> dict[str, Any]:
    status = str(status).strip().lower()
    if status not in ("draft", "sent", "received", "cancelled"):
        raise ValueError("status must be one of: draft, sent, received, cancelled")
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if row is None:
            raise ValueError("Purchase order not found")
        row = row_to_dict(row)
        if row["status"] == "received":
            raise ValueError("Cannot change status of a received purchase order")
        if status == "received" and row["status"] != "received":
            # Create journal entry for the purchase
            if _is_period_closed(conn, row["business_id"], row["order_date"]):
                raise ValueError("Cannot post to a closed accounting period")
            entry_cursor = conn.execute(
                "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'posted', ?, ?)",
                (row["business_id"], row["order_date"], row["po_number"], f"Purchase order {row['po_number']}", now, now),
            )
            entry_id = entry_cursor.lastrowid
            conn.execute("INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                         (entry_id, row["expense_account_id"], f"PO {row['po_number']}", row["total_amount"], 0))
            conn.execute("INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                         (entry_id, row["payment_account_id"], f"PO {row['po_number']}", 0, row["total_amount"]))
            conn.execute("UPDATE purchase_orders SET status = ?, journal_entry_id = ?, updated_at = ? WHERE id = ?", (status, entry_id, now, po_id))
        else:
            conn.execute("UPDATE purchase_orders SET status = ?, updated_at = ? WHERE id = ?", (status, now, po_id))
        conn.commit()
        return _get_purchase_order_detail(conn, po_id)


def delete_purchase_order(po_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT status FROM purchase_orders WHERE id = ?", (po_id,)).fetchone()
        if row is None:
            raise ValueError("Purchase order not found")
        if row["status"] == "received":
            raise ValueError("Cannot delete a received purchase order")
        conn.execute("DELETE FROM purchase_orders WHERE id = ?", (po_id,))
        conn.commit()


def fixed_asset_register(business_id: int) -> dict[str, Any]:
    """Comprehensive fixed asset register with current book values."""
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT da.*, a.code AS asset_code, a.name AS asset_account_name,
               aa.code AS accumulated_code, aa.name AS accumulated_account_name,
               dp.code AS depreciation_code, dp.name AS depreciation_account_name
               FROM depreciation_assets da
               LEFT JOIN accounts a ON a.id = da.asset_account_id
               LEFT JOIN accounts aa ON aa.id = da.accumulated_account_id
               LEFT JOIN accounts dp ON dp.id = da.depreciation_account_id
               WHERE da.business_id = ?
               ORDER BY da.acquisition_date DESC, da.id DESC""",
            (business_id,),
        ).fetchall()
        assets = []
        total_cost = 0.0
        total_accumulated = 0.0
        total_book_value = 0.0
        for row in rows:
            asset = row_to_dict(row)
            # Calculate accumulated depreciation from posted entries
            dep_rows = conn.execute(
                """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS accumulated
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND jl.account_id = ?""",
                (business_id, asset["accumulated_account_id"]),
            ).fetchone()
            accumulated_dep = round(dep_rows["accumulated"], 2)
            book_value = round(asset["cost"] - accumulated_dep, 2)
            total_cost = round(total_cost + asset["cost"], 2)
            total_accumulated = round(total_accumulated + accumulated_dep, 2)
            total_book_value = round(total_book_value + book_value, 2)
            asset["accumulated_depreciation"] = accumulated_dep
            asset["book_value"] = book_value
            assets.append(asset)
        return {
            "assets": assets,
            "total_assets": len(assets),
            "total_cost": total_cost,
            "total_accumulated_depreciation": total_accumulated,
            "total_book_value": total_book_value,
        }


def dispose_fixed_asset(asset_id: int, disposal_date: str, disposal_price: float, gain_loss_account_id: int) -> dict[str, Any]:
    """Dispose of a fixed asset, creating journal entries for the disposal."""
    disposal_date = _date(disposal_date, "disposal_date")
    try:
        disposal_price = float(disposal_price)
    except (TypeError, ValueError):
        raise ValueError("disposal_price must be a number")
    try:
        gain_loss_account_id = int(gain_loss_account_id)
    except (TypeError, ValueError):
        raise ValueError("gain_loss_account_id is required")
    now = now_utc()
    with get_db() as conn:
        asset = conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (asset_id,)).fetchone()
        if asset is None:
            raise ValueError("Asset not found")
        asset = row_to_dict(asset)
        if asset["status"] not in ("active", "fully_depreciated"):
            raise ValueError("Asset is not active or fully depreciated")
        if _is_period_closed(conn, asset["business_id"], disposal_date):
            raise ValueError("Cannot post to a closed accounting period")
        # Verify gain/loss account
        acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (gain_loss_account_id, asset["business_id"])).fetchone()
        if acct is None:
            raise ValueError("Gain/loss account not found for this business")
        # Calculate accumulated depreciation
        dep_rows = conn.execute(
            """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS accumulated
               FROM journal_lines jl
               JOIN journal_entries je ON je.id = jl.entry_id
               WHERE je.business_id = ? AND je.status = 'posted'
               AND jl.account_id = ?""",
            (asset["business_id"], asset["accumulated_account_id"]),
        ).fetchone()
        accumulated_dep = round(dep_rows["accumulated"], 2)
        book_value = round(asset["cost"] - accumulated_dep, 2)
        gain_loss = round(disposal_price - book_value, 2)
        # Create disposal journal entry
        entry_cursor = conn.execute(
            "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'posted', ?, ?)",
            (asset["business_id"], disposal_date, f"DISP-{asset['id']}", f"Disposal of {asset['name']}", now, now),
        )
        entry_id = entry_cursor.lastrowid
        # Credit asset account (remove cost)
        conn.execute("INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                     (entry_id, asset["asset_account_id"], f"Dispose {asset['name']}", 0, asset["cost"]))
        # Debit accumulated depreciation (remove accumulated dep) - skip if 0
        if accumulated_dep > 0:
            conn.execute("INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                         (entry_id, asset["accumulated_account_id"], f"Dispose {asset['name']}", accumulated_dep, 0))
        # Debit cash/receivable for disposal price - skip if 0
        if disposal_price > 0:
            conn.execute("INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                         (entry_id, gain_loss_account_id, f"Dispose {asset['name']}", disposal_price, 0))
        # Credit/Debit gain or loss - skip if 0
        if gain_loss > 0:
            conn.execute("INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                         (entry_id, gain_loss_account_id, f"Gain on disposal {asset['name']}", 0, gain_loss))
        elif gain_loss < 0:
            conn.execute("INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                         (entry_id, gain_loss_account_id, f"Loss on disposal {asset['name']}", abs(gain_loss), 0))
        # Mark asset as disposed
        conn.execute("UPDATE depreciation_assets SET status = 'disposed', updated_at = ? WHERE id = ?", (now, asset_id))
        conn.commit()
        return {
            "disposed": True,
            "asset_id": asset_id,
            "disposal_price": disposal_price,
            "book_value": book_value,
            "gain_loss": gain_loss,
            "entry_id": entry_id,
        }


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
            for rec in recurring_rows:
                rec = row_to_dict(rec)
                next_date = datetime.date.fromisoformat(rec["next_due_date"]) if rec["next_due_date"] else None
                if next_date and month_date <= next_date.replace(day=1) <= month_end:
                    outflows = round(outflows + rec["amount"], 2)
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
