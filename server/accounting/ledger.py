from __future__ import annotations

import calendar
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


def _entry_lines(conn: sqlite3.Connection, entry_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT journal_lines.*, accounts.code AS account_code, accounts.name AS account_name
        FROM journal_lines JOIN accounts ON accounts.id = journal_lines.account_id
        WHERE entry_id = ? ORDER BY journal_lines.id""",
        (entry_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


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


def _post_operation_entry(conn: sqlite3.Connection, business_id: int, entry_date: str, reference: str, description: str, lines: list[tuple[int, float, float]], depreciation_asset_id: int | None = None) -> int:
    """Single funnel for operation-generated posted journal entries.

    Enforces the closed-period invariant here so no caller can post into a
    closed accounting period by mistake.
    """
    if _is_period_closed(conn, business_id, entry_date):
        raise ValueError("Cannot post to a closed accounting period")
    now = now_utc()
    cursor = conn.execute(
        "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, depreciation_asset_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'posted', ?, ?, ?)",
        (business_id, entry_date, reference, description, depreciation_asset_id, now, now),
    )
    entry_id = cursor.lastrowid
    conn.executemany(
        "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
        [(entry_id, account_id, description, debit, credit) for account_id, debit, credit in lines],
    )
    return entry_id


def _is_period_closed(conn, business_id: int, entry_date: str) -> bool:
    row = conn.execute(
        "SELECT id FROM closing_periods WHERE business_id = ? AND ? >= period_start AND ? <= period_end",
        (business_id, entry_date, entry_date),
    ).fetchone()
    return row is not None


def _add_months(d: datetime.date, months: int) -> datetime.date:
    """Advance by whole months, clamping the day to the target month's end
    so dates like Jan 31 or Feb 29 never produce an invalid date."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


_RECURRENCE_MONTH_STEPS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def _recurrence_occurrence(start: datetime.date, frequency: str, n: int) -> datetime.date:
    """Nth scheduled occurrence (0-based) computed from the original
    start_date anchor, so a clamped month never shifts the schedule."""
    if frequency == "weekly":
        return start + datetime.timedelta(weeks=n)
    return _add_months(start, n * _RECURRENCE_MONTH_STEPS[frequency])


def _iter_occurrences(start_date: str, frequency: str, first: str | None = None):
    """Yield scheduled occurrence dates (ISO strings) anchored to the
    original start_date. When `first` is given, iteration begins at the
    first occurrence on or after that date."""
    start = datetime.date.fromisoformat(start_date)
    n = 0
    if first is not None:
        first_d = datetime.date.fromisoformat(first)
        if first_d > start:
            if frequency == "weekly":
                n = (first_d - start).days // 7
            else:
                step = _RECURRENCE_MONTH_STEPS[frequency]
                # n is the occurrence index — _recurrence_occurrence already
                # multiplies it by step, so do not apply step twice here.
                n = ((first_d.year - start.year) * 12 + (first_d.month - start.month)) // step
            while _recurrence_occurrence(start, frequency, n) < first_d:
                n += 1
    while True:
        yield _recurrence_occurrence(start, frequency, n).isoformat()
        n += 1


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


def list_1099_vendors(business_id: int) -> list[dict[str, Any]]:
    """List all vendors marked as 1099-eligible."""
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            "SELECT * FROM accounting_contacts WHERE business_id = ? AND is_1099 = 1 AND contact_type IN ('vendor', 'both') ORDER BY name",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def update_contact_1099(contact_id: int, is_1099: bool, tax_id: str = "") -> dict[str, Any]:
    """Update a contact's 1099 eligibility and tax ID."""
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM accounting_contacts WHERE id = ?", (contact_id,)).fetchone()
        if row is None:
            raise ValueError("Contact not found")
        conn.execute("UPDATE accounting_contacts SET is_1099 = ?, tax_id = ?, updated_at = ? WHERE id = ?",
                     (1 if is_1099 else 0, str(tax_id).strip(), now, contact_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM accounting_contacts WHERE id = ?", (contact_id,)).fetchone())


def report_1099(business_id: int, tax_year: int) -> dict[str, Any]:
    """Generate 1099 report: total payments to 1099 vendors in a tax year."""
    with get_db() as conn:
        _require_business(conn, business_id)
        vendors = conn.execute(
            "SELECT * FROM accounting_contacts WHERE business_id = ? AND is_1099 = 1 AND contact_type IN ('vendor', 'both') ORDER BY name",
            (business_id,),
        ).fetchall()
        period_start = f"{tax_year}-01-01"
        period_end = f"{tax_year}-12-31"
        entries = []
        total_payments = 0.0
        for vendor in vendors:
            vendor = row_to_dict(vendor)
            # Sum expenses paid to this vendor in the tax year
            exp_rows = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) AS total
                   FROM expenses WHERE business_id = ? AND vendor_id = ? AND expense_date >= ? AND expense_date <= ?""",
                (business_id, vendor["id"], period_start, period_end),
            ).fetchone()
            payments = round(exp_rows["total"], 2)
            if payments > 0:
                total_payments = round(total_payments + payments, 2)
                entries.append({
                    "vendor_id": vendor["id"],
                    "vendor_name": vendor["name"],
                    "tax_id": vendor["tax_id"],
                    "total_payments": payments,
                })
        return {
            "tax_year": tax_year,
            "vendor_count": len(entries),
            "total_payments": total_payments,
            "entries": entries,
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


def list_chart_templates() -> list[dict[str, Any]]:
    """List available chart of accounts templates."""
    result = []
    for key, accounts in CHART_TEMPLATES.items():
        result.append({
            "template": key,
            "account_count": len(accounts),
            "account_types": list(set(a["account_type"] for a in accounts)),
        })
    return result


def get_chart_template(template_name: str) -> dict[str, Any]:
    """Get the details of a specific chart of accounts template."""
    template_name = template_name.strip().lower()
    if template_name not in CHART_TEMPLATES:
        raise ValueError(f"Template '{template_name}' not found. Available: {', '.join(CHART_TEMPLATES.keys())}")
    return {
        "template": template_name,
        "accounts": CHART_TEMPLATES[template_name],
        "account_count": len(CHART_TEMPLATES[template_name]),
    }


def apply_chart_template(business_id: int, template_name: str) -> dict[str, Any]:
    """Apply a chart of accounts template to a business, creating all accounts."""
    template_name = template_name.strip().lower()
    if template_name not in CHART_TEMPLATES:
        raise ValueError(f"Template '{template_name}' not found. Available: {', '.join(CHART_TEMPLATES.keys())}")
    now = now_utc()
    created = []
    skipped = []
    with get_db() as conn:
        _require_business(conn, business_id)
        for acct in CHART_TEMPLATES[template_name]:
            existing = conn.execute("SELECT id FROM accounts WHERE business_id = ? AND code = ?", (business_id, acct["code"])).fetchone()
            if existing:
                skipped.append(acct)
                continue
            cursor = conn.execute(
                "INSERT INTO accounts (business_id, code, name, account_type, active, created_at, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                (business_id, acct["code"], acct["name"], acct["account_type"], now, now),
            )
            created.append({**acct, "id": cursor.lastrowid})
        conn.commit()
        return {
            "template": template_name,
            "created_count": len(created),
            "skipped_count": len(skipped),
            "created": created,
            "skipped": skipped,
        }
CHART_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "sole_proprietor": [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "1100", "name": "Accounts Receivable", "account_type": "asset"},
        {"code": "1200", "name": "Inventory", "account_type": "asset"},
        {"code": "1500", "name": "Equipment", "account_type": "asset"},
        {"code": "1510", "name": "Accumulated Depreciation", "account_type": "asset"},
        {"code": "2000", "name": "Accounts Payable", "account_type": "liability"},
        {"code": "2100", "name": "Sales Tax Payable", "account_type": "liability"},
        {"code": "2200", "name": "Loans Payable", "account_type": "liability"},
        {"code": "3000", "name": "Owner's Capital", "account_type": "equity"},
        {"code": "3100", "name": "Owner's Draw", "account_type": "equity"},
        {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
        {"code": "4100", "name": "Service Revenue", "account_type": "revenue"},
        {"code": "5000", "name": "Cost of Goods Sold", "account_type": "expense"},
        {"code": "6000", "name": "Rent Expense", "account_type": "expense"},
        {"code": "6100", "name": "Utilities Expense", "account_type": "expense"},
        {"code": "6200", "name": "Wages Expense", "account_type": "expense"},
        {"code": "6300", "name": "Office Supplies", "account_type": "expense"},
        {"code": "6400", "name": "Advertising Expense", "account_type": "expense"},
        {"code": "6500", "name": "Insurance Expense", "account_type": "expense"},
        {"code": "6600", "name": "Depreciation Expense", "account_type": "expense"},
    ],
    "llc": [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "1100", "name": "Accounts Receivable", "account_type": "asset"},
        {"code": "1200", "name": "Inventory", "account_type": "asset"},
        {"code": "1500", "name": "Equipment", "account_type": "asset"},
        {"code": "1510", "name": "Accumulated Depreciation", "account_type": "asset"},
        {"code": "2000", "name": "Accounts Payable", "account_type": "liability"},
        {"code": "2100", "name": "Sales Tax Payable", "account_type": "liability"},
        {"code": "2200", "name": "Loans Payable", "account_type": "liability"},
        {"code": "2300", "name": "Payroll Liabilities", "account_type": "liability"},
        {"code": "3000", "name": "Member Capital", "account_type": "equity"},
        {"code": "3100", "name": "Member Distributions", "account_type": "equity"},
        {"code": "3200", "name": "Retained Earnings", "account_type": "equity"},
        {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
        {"code": "4100", "name": "Service Revenue", "account_type": "revenue"},
        {"code": "5000", "name": "Cost of Goods Sold", "account_type": "expense"},
        {"code": "6000", "name": "Rent Expense", "account_type": "expense"},
        {"code": "6100", "name": "Utilities Expense", "account_type": "expense"},
        {"code": "6200", "name": "Salaries Expense", "account_type": "expense"},
        {"code": "6300", "name": "Office Supplies", "account_type": "expense"},
        {"code": "6400", "name": "Advertising Expense", "account_type": "expense"},
        {"code": "6500", "name": "Insurance Expense", "account_type": "expense"},
        {"code": "6600", "name": "Depreciation Expense", "account_type": "expense"},
        {"code": "6700", "name": "Legal & Professional", "account_type": "expense"},
    ],
    "corporation": [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "1100", "name": "Accounts Receivable", "account_type": "asset"},
        {"code": "1200", "name": "Inventory", "account_type": "asset"},
        {"code": "1300", "name": "Prepaid Expenses", "account_type": "asset"},
        {"code": "1500", "name": "Equipment", "account_type": "asset"},
        {"code": "1510", "name": "Accumulated Depreciation", "account_type": "asset"},
        {"code": "1600", "name": "Buildings", "account_type": "asset"},
        {"code": "1610", "name": "Accumulated Depreciation - Buildings", "account_type": "asset"},
        {"code": "2000", "name": "Accounts Payable", "account_type": "liability"},
        {"code": "2100", "name": "Sales Tax Payable", "account_type": "liability"},
        {"code": "2200", "name": "Loans Payable", "account_type": "liability"},
        {"code": "2300", "name": "Payroll Tax Liabilities", "account_type": "liability"},
        {"code": "2400", "name": "Accrued Expenses", "account_type": "liability"},
        {"code": "3000", "name": "Common Stock", "account_type": "equity"},
        {"code": "3100", "name": "Additional Paid-in Capital", "account_type": "equity"},
        {"code": "3200", "name": "Retained Earnings", "account_type": "equity"},
        {"code": "3300", "name": "Dividends", "account_type": "equity"},
        {"code": "4000", "name": "Sales Revenue", "account_type": "revenue"},
        {"code": "4100", "name": "Service Revenue", "account_type": "revenue"},
        {"code": "4200", "name": "Interest Income", "account_type": "revenue"},
        {"code": "5000", "name": "Cost of Goods Sold", "account_type": "expense"},
        {"code": "6000", "name": "Rent Expense", "account_type": "expense"},
        {"code": "6100", "name": "Utilities Expense", "account_type": "expense"},
        {"code": "6200", "name": "Salaries Expense", "account_type": "expense"},
        {"code": "6300", "name": "Office Supplies", "account_type": "expense"},
        {"code": "6400", "name": "Advertising Expense", "account_type": "expense"},
        {"code": "6500", "name": "Insurance Expense", "account_type": "expense"},
        {"code": "6600", "name": "Depreciation Expense", "account_type": "expense"},
        {"code": "6700", "name": "Legal & Professional", "account_type": "expense"},
        {"code": "6800", "name": "Income Tax Expense", "account_type": "expense"},
    ],
    "nonprofit": [
        {"code": "1000", "name": "Cash", "account_type": "asset"},
        {"code": "1100", "name": "Grants Receivable", "account_type": "asset"},
        {"code": "1200", "name": "Pledges Receivable", "account_type": "asset"},
        {"code": "1500", "name": "Equipment", "account_type": "asset"},
        {"code": "1510", "name": "Accumulated Depreciation", "account_type": "asset"},
        {"code": "2000", "name": "Accounts Payable", "account_type": "liability"},
        {"code": "2200", "name": "Loans Payable", "account_type": "liability"},
        {"code": "2300", "name": "Payroll Liabilities", "account_type": "liability"},
        {"code": "3000", "name": "Unrestricted Net Assets", "account_type": "equity"},
        {"code": "3100", "name": "Temporarily Restricted Net Assets", "account_type": "equity"},
        {"code": "3200", "name": "Permanently Restricted Net Assets", "account_type": "equity"},
        {"code": "4000", "name": "Donation Revenue", "account_type": "revenue"},
        {"code": "4100", "name": "Grant Revenue", "account_type": "revenue"},
        {"code": "4200", "name": "Program Service Revenue", "account_type": "revenue"},
        {"code": "5000", "name": "Program Expenses", "account_type": "expense"},
        {"code": "6000", "name": "Management & General", "account_type": "expense"},
        {"code": "6100", "name": "Fundraising Expense", "account_type": "expense"},
        {"code": "6200", "name": "Rent Expense", "account_type": "expense"},
        {"code": "6300", "name": "Utilities Expense", "account_type": "expense"},
        {"code": "6400", "name": "Salaries Expense", "account_type": "expense"},
        {"code": "6500", "name": "Office Supplies", "account_type": "expense"},
        {"code": "6600", "name": "Insurance Expense", "account_type": "expense"},
    ],
}


