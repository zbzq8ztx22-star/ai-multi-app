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
