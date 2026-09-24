from __future__ import annotations

import sqlite3
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _date, _is_period_closed, _require_business


def list_closing_periods(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            "SELECT * FROM closing_periods WHERE business_id = ? ORDER BY period_end DESC",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


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
