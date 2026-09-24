from __future__ import annotations

import sqlite3
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _account_for_business, _date, _is_period_closed, _post_operation_entry, _require_business


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
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if _is_period_closed(conn, business_id, credit_date):
            raise ValueError("Cannot post to a closed accounting period")
        if invoice_id is not None:
            inv = conn.execute("SELECT * FROM invoices WHERE id = ? AND business_id = ?", (invoice_id, business_id)).fetchone()
            if inv is None:
                raise ValueError("Invoice not found for this business")
            if inv["status"] != "open":
                raise ValueError("Credit notes can only be applied to open invoices")
            if customer_id is None:
                customer_id = inv["customer_id"]
            elif int(customer_id) != inv["customer_id"]:
                raise ValueError("Credit note customer does not match the invoice customer")
            # Linked credit notes reverse the invoice's own accounts;
            # caller-supplied account ids are ignored
            receivable_account_id = inv["receivable_account_id"]
            revenue_account_id = inv["revenue_account_id"]
            # A credit note may not exceed the remaining invoice balance
            balance = round(inv["amount"] - inv["amount_paid"], 2)
            if amount > balance:
                raise ValueError("Credit note amount exceeds the remaining invoice balance")
        else:
            receivable_account_id = _account_for_business(conn, business_id, receivable_account_id, {"asset"}, "receivable_account_id")
            revenue_account_id = _account_for_business(conn, business_id, revenue_account_id, {"revenue"}, "revenue_account_id")
        # Validate customer if provided
        if customer_id is not None:
            cust = conn.execute("SELECT * FROM accounting_contacts WHERE id = ? AND business_id = ?", (customer_id, business_id)).fetchone()
            if cust is None:
                raise ValueError("Customer not found for this business")
        # Create reversing journal entry: credit receivable (reduce AR), debit revenue (reduce revenue)
        entry_id = _post_operation_entry(
            conn, business_id, credit_date, credit_number,
            f"Credit note {credit_number}",
            [(revenue_account_id, amount, 0), (receivable_account_id, 0, amount)],
        )
        # If linked to invoice, apply the credit and mark it paid when the
        # remaining balance reaches zero
        if invoice_id is not None:
            new_paid = round(inv["amount_paid"] + amount, 2)
            new_status = "paid" if new_paid >= inv["amount"] else inv["status"]
            conn.execute("UPDATE invoices SET amount_paid = ?, status = ?, updated_at = ? WHERE id = ?",
                         (new_paid, new_status, now, invoice_id))
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
        _post_operation_entry(
            conn, business_id, now[:10], f"VOID-{row['credit_number']}",
            f"Void credit note {row['credit_number']}",
            [(row["receivable_account_id"], row["amount"], 0), (row["revenue_account_id"], 0, row["amount"])],
        )
        # If linked to invoice, reverse the applied credit and reopen the
        # invoice when the remaining balance becomes positive again
        if row["invoice_id"] is not None:
            inv = conn.execute("SELECT amount, amount_paid, status FROM invoices WHERE id = ?", (row["invoice_id"],)).fetchone()
            if inv is not None:
                new_paid = round(max(inv["amount_paid"] - row["amount"], 0), 2)
                new_status = "open" if inv["status"] == "paid" and new_paid < inv["amount"] else inv["status"]
                conn.execute("UPDATE invoices SET amount_paid = ?, status = ?, updated_at = ? WHERE id = ?",
                             (new_paid, new_status, now, row["invoice_id"]))
        conn.execute("UPDATE credit_notes SET status = 'void', updated_at = ? WHERE id = ?", (now, credit_id))
        conn.commit()
        return get_credit_note_detail(business_id, credit_id)
