from __future__ import annotations

import sqlite3
from typing import Any

from payroll.db import get_db, now_utc, row_to_dict
from .calculator import AMOUNT_FIELDS, calculate_personal_return

STATUSES = {"draft", "reviewed", "filed"}


def list_returns(taxpayer_id: int | None = None) -> list[dict[str, Any]]:
    query = "SELECT tax_returns.*, taxpayers.legal_name AS taxpayer_name FROM tax_returns JOIN taxpayers ON taxpayers.id = tax_returns.taxpayer_id"
    params: tuple[Any, ...] = ()
    if taxpayer_id is not None:
        query += " WHERE taxpayer_id = ?"
        params = (taxpayer_id,)
    query += " ORDER BY tax_year DESC, taxpayer_name"
    with get_db() as conn:
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def get_return(return_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM tax_returns WHERE id = ?", (return_id,)).fetchone()
        return row_to_dict(row) if row else None


def save_return(data: dict[str, Any], return_id: int | None = None) -> dict[str, Any]:
    try:
        taxpayer_id = int(data.get("taxpayer_id"))
        tax_year = int(data.get("tax_year", 2025))
    except (TypeError, ValueError):
        raise ValueError("taxpayer_id and tax_year are required")
    status = data.get("status", "draft")
    if status not in STATUSES:
        raise ValueError("Invalid status")
    with get_db() as conn:
        taxpayer = conn.execute("SELECT * FROM taxpayers WHERE id = ?", (taxpayer_id,)).fetchone()
        if taxpayer is None:
            raise ValueError("Taxpayer not found")
    filing_status = data.get("filing_status") or taxpayer["filing_status"]
    residence_state = str(data.get("residence_state") or taxpayer["residence_state"]).strip().upper()
    payload = {**data, "tax_year": tax_year, "filing_status": filing_status}
    calculation = calculate_personal_return(payload)
    amounts = {field: float(data.get(field, 0) or 0) for field in AMOUNT_FIELDS}
    now = now_utc()
    columns = ["taxpayer_id", "tax_year", "status", "filing_status", "residence_state", *AMOUNT_FIELDS, *calculation.keys(), "updated_at"]
    values = [taxpayer_id, tax_year, status, filing_status, residence_state, *[amounts[field] for field in AMOUNT_FIELDS], *calculation.values(), now]
    with get_db() as conn:
        if return_id is None:
            columns.append("created_at")
            values.append(now)
            placeholders = ", ".join("?" for _ in columns)
            try:
                cursor = conn.execute(f"INSERT INTO tax_returns ({', '.join(columns)}) VALUES ({placeholders})", values)
            except sqlite3.IntegrityError as exc:
                if "UNIQUE constraint" in str(exc):
                    raise ValueError("A return already exists for this taxpayer and year")
                raise
            return_id = cursor.lastrowid
        else:
            if conn.execute("SELECT id FROM tax_returns WHERE id = ?", (return_id,)).fetchone() is None:
                raise ValueError("Tax return not found")
            assignments = ", ".join(f"{column} = ?" for column in columns)
            conn.execute(f"UPDATE tax_returns SET {assignments} WHERE id = ?", [*values, return_id])
        conn.commit()
        row = conn.execute("SELECT * FROM tax_returns WHERE id = ?", (return_id,)).fetchone()
        return row_to_dict(row)


TAX_PAYMENT_TYPES = {"federal_estimated", "state_estimated", "federal_payroll", "state_payroll", "sales", "other"}


def _require_business(conn, business_id: int) -> None:
    row = conn.execute("SELECT id FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if row is None:
        raise ValueError("Business not found")


def list_tax_payments(business_id: int, tax_type: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = "SELECT * FROM tax_payments WHERE business_id = ?"
        params: list[Any] = [business_id]
        if tax_type:
            query += " AND tax_type = ?"
            params.append(tax_type)
        query += " ORDER BY payment_date DESC, id DESC"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_tax_payment(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    tax_type = str(data.get("tax_type", "")).strip().lower()
    if tax_type not in TAX_PAYMENT_TYPES:
        raise ValueError(f"tax_type must be one of: {', '.join(sorted(TAX_PAYMENT_TYPES))}")
    payment_date = str(data.get("payment_date", "")).strip()
    if not payment_date:
        raise ValueError("payment_date is required")
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        raise ValueError("amount must be a number")
    if amount <= 0:
        raise ValueError("amount must be positive")
    period_start = str(data.get("period_start", "")).strip()
    period_end = str(data.get("period_end", "")).strip()
    if not period_start or not period_end:
        raise ValueError("period_start and period_end are required")
    if period_end < period_start:
        raise ValueError("period_end cannot be before period_start")
    reference = str(data.get("reference", "")).strip()
    notes = str(data.get("notes", "")).strip()
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        cursor = conn.execute(
            "INSERT INTO tax_payments (business_id, tax_type, payment_date, amount, period_start, period_end, reference, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (business_id, tax_type, payment_date, amount, period_start, period_end, reference, notes, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM tax_payments WHERE id = ?", (cursor.lastrowid,)).fetchone())


def delete_tax_payment(payment_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM tax_payments WHERE id = ?", (payment_id,)).fetchone() is None:
            raise ValueError("Tax payment not found")
        conn.execute("DELETE FROM tax_payments WHERE id = ?", (payment_id,))
        conn.commit()


def tax_payment_summary(business_id: int, year: int | None = None) -> dict[str, Any]:
    """Summarize tax payments by type for a given year."""
    with get_db() as conn:
        _require_business(conn, business_id)
        if year:
            query = "SELECT tax_type, COUNT(*) as count, SUM(amount) as total FROM tax_payments WHERE business_id = ? AND payment_date >= ? AND payment_date <= ? GROUP BY tax_type"
            params = [business_id, f"{year}-01-01", f"{year}-12-31"]
        else:
            query = "SELECT tax_type, COUNT(*) as count, SUM(amount) as total FROM tax_payments WHERE business_id = ? GROUP BY tax_type"
            params = [business_id]
        rows = conn.execute(query, params).fetchall()
        summary = {}
        total = 0.0
        for row in rows:
            summary[row["tax_type"]] = {"count": row["count"], "total": round(row["total"], 2)}
            total += row["total"]
        return {"year": year, "by_type": summary, "total_paid": round(total, 2)}
