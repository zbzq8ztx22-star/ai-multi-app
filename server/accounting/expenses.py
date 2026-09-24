from __future__ import annotations

import datetime
import sqlite3
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _account_for_business, _date, _is_period_closed, _iter_occurrences, _money, _post_operation_entry, _require_business


def list_expenses(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("""SELECT expenses.*, accounting_contacts.name AS vendor_name FROM expenses
            LEFT JOIN accounting_contacts ON accounting_contacts.id = expenses.vendor_id
            WHERE expenses.business_id = ? ORDER BY expense_date DESC, id DESC""", (business_id,)).fetchall()
        return [row_to_dict(row) for row in rows]


def _create_expense(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    """Validate and insert an expense inside an existing transaction so
    callers (e.g. recurring-expense posting) stay atomic with other writes."""
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
    approval_status = str(data.get("approval_status", "approved")).strip().lower()
    if approval_status not in ("pending", "approved", "rejected"):
        raise ValueError("approval_status must be one of: pending, approved, rejected")
    now = now_utc()
    _require_business(conn, business_id)
    if vendor_id:
        contact = conn.execute("SELECT contact_type FROM accounting_contacts WHERE id = ? AND business_id = ?", (vendor_id, business_id)).fetchone()
        if contact is None or contact["contact_type"] not in ("vendor", "both"):
            raise ValueError("Vendor not found for this business")
    expense_account = _account_for_business(conn, business_id, data.get("expense_account_id"), {"expense"}, "expense_account_id")
    payment_account = _account_for_business(conn, business_id, data.get("payment_account_id"), {"asset", "liability"}, "payment_account_id")
    reference = str(data.get("reference", "")).strip()
    if approval_status == "approved":
        entry_id = _post_operation_entry(conn, business_id, expense_date, reference, description, [(expense_account, amount, 0), (payment_account, 0, amount)])
    else:
        entry_id = None
    cursor = conn.execute("""INSERT INTO expenses
        (business_id, vendor_id, expense_date, reference, description, amount, expense_account_id, payment_account_id, journal_entry_id, approval_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (business_id, vendor_id, expense_date, reference, description, amount, expense_account, payment_account, entry_id, approval_status, now))
    return row_to_dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (cursor.lastrowid,)).fetchone())


def create_expense(data: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        result = _create_expense(conn, data)
        conn.commit()
        return result


def approve_expense(expense_id: int, approver: str) -> dict[str, Any]:
    """Approve a pending expense and create the journal entry."""
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if row is None:
            raise ValueError("Expense not found")
        row = row_to_dict(row)
        if row["approval_status"] != "pending":
            raise ValueError("Expense is not pending")
        if _is_period_closed(conn, row["business_id"], row["expense_date"]):
            raise ValueError("Cannot post to a closed accounting period")
        entry_id = _post_operation_entry(conn, row["business_id"], row["expense_date"], row["reference"], row["description"],
                                          [(row["expense_account_id"], row["amount"], 0), (row["payment_account_id"], 0, row["amount"])])
        conn.execute("UPDATE expenses SET approval_status = 'approved', approved_by = ?, approved_at = ?, journal_entry_id = ? WHERE id = ?",
                     (approver, now, entry_id, expense_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())


def reject_expense(expense_id: int, approver: str) -> dict[str, Any]:
    """Reject a pending expense."""
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
        if row is None:
            raise ValueError("Expense not found")
        row = row_to_dict(row)
        if row["approval_status"] != "pending":
            raise ValueError("Expense is not pending")
        conn.execute("UPDATE expenses SET approval_status = 'rejected', approved_by = ?, approved_at = ? WHERE id = ?",
                     (approver, now, expense_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone())


def list_pending_expenses(business_id: int) -> list[dict[str, Any]]:
    """List all pending expenses for a business."""
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("""SELECT expenses.*, accounting_contacts.name AS vendor_name FROM expenses
            LEFT JOIN accounting_contacts ON accounting_contacts.id = expenses.vendor_id
            WHERE expenses.business_id = ? AND expenses.approval_status = 'pending'
            ORDER BY expenses.expense_date DESC, expenses.id DESC""", (business_id,)).fetchall()
        return [row_to_dict(row) for row in rows]


RECURRING_FREQUENCIES = {"weekly", "monthly", "quarterly", "yearly"}


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
            # Catch up every overdue occurrence, anchored to start_date so a
            # clamped month (e.g. Jan 31 -> Feb 28) does not shift the schedule.
            occurrences = _iter_occurrences(row["start_date"], row["frequency"], first=row["next_date"])
            occ = next(occurrences)
            last_posted = None
            while occ <= as_of and (row["end_date"] is None or occ <= row["end_date"]):
                expense = _create_expense(conn, {
                    "business_id": business_id,
                    "vendor_id": row["vendor_id"],
                    "expense_date": occ,
                    "reference": f"RECUR-{row['id']}",
                    "description": row["description"],
                    "amount": row["amount"],
                    "expense_account_id": row["expense_account_id"],
                    "payment_account_id": row["payment_account_id"],
                })
                posted.append(expense)
                last_posted = occ
                occ = next(occurrences)
            if last_posted is not None:
                active = 0 if row["end_date"] and occ > row["end_date"] else 1
                conn.execute("UPDATE recurring_expenses SET last_posted_date = ?, next_date = ?, active = ?, updated_at = ? WHERE id = ?",
                             (last_posted, occ, active, now_utc(), row["id"]))
        conn.commit()
    return posted


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
