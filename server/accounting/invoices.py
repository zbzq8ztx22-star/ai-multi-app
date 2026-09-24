from __future__ import annotations

import datetime
import sqlite3
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _account_for_business, _date, _money, _post_operation_entry, _require_business


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
        business_id = int(data.get("business_id"))
        customer_id = int(data.get("customer_id"))
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
    d = datetime.date.fromisoformat(issue_date)
    due = d + datetime.timedelta(days=net_days)
    return due.isoformat()


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
