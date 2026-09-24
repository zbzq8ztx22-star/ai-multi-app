from __future__ import annotations

import sqlite3
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _date, _post_operation_entry, _require_business


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
            entry_id = _post_operation_entry(
                conn, row["business_id"], row["order_date"], row["po_number"],
                f"Purchase order {row['po_number']}",
                [(row["expense_account_id"], row["total_amount"], 0), (row["payment_account_id"], 0, row["total_amount"])],
            )
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
