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
