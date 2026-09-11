from __future__ import annotations

from typing import Any

from payroll.db import get_db, now_utc, row_to_dict


def _require_business(conn, business_id: int) -> None:
    row = conn.execute("SELECT id FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if row is None:
        raise ValueError("Business not found")


def list_currencies(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("SELECT * FROM currencies WHERE business_id = ? ORDER BY is_base DESC, code", (business_id,)).fetchall()
        return [row_to_dict(row) for row in rows]


def create_currency(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    code = str(data.get("code", "")).strip().upper()
    name = str(data.get("name", "")).strip()
    symbol = str(data.get("symbol", "$")).strip() or "$"
    is_base = 1 if data.get("is_base") else 0
    if not code or not name:
        raise ValueError("code and name are required")
    if len(code) != 3:
        raise ValueError("code must be 3 characters")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if is_base:
            existing_base = conn.execute("SELECT id FROM currencies WHERE business_id = ? AND is_base = 1", (business_id,)).fetchone()
            if existing_base:
                raise ValueError("Business already has a base currency")
        try:
            cursor = conn.execute(
                "INSERT INTO currencies (business_id, code, name, symbol, is_base, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (business_id, code, name, symbol, is_base, now),
            )
        except Exception:
            raise ValueError("Currency code already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM currencies WHERE id = ?", (cursor.lastrowid,)).fetchone())


def set_exchange_rate(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    try:
        from_id = int(data.get("from_currency_id"))
        to_id = int(data.get("to_currency_id"))
    except (TypeError, ValueError):
        raise ValueError("from_currency_id and to_currency_id are required")
    rate = float(data.get("rate", 0))
    if rate <= 0:
        raise ValueError("rate must be positive")
    rate_date = str(data.get("rate_date", "")).strip()
    if not rate_date:
        raise ValueError("rate_date is required")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        for cid in (from_id, to_id):
            row = conn.execute("SELECT id FROM currencies WHERE id = ? AND business_id = ?", (cid, business_id)).fetchone()
            if row is None:
                raise ValueError("Currency not found for this business")
        cursor = conn.execute(
            "INSERT INTO exchange_rates (business_id, from_currency_id, to_currency_id, rate, rate_date, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (business_id, from_id, to_id, rate, rate_date, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM exchange_rates WHERE id = ?", (cursor.lastrowid,)).fetchone())


def list_exchange_rates(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT er.*, fc.code AS from_code, tc.code AS to_code
               FROM exchange_rates er
               JOIN currencies fc ON fc.id = er.from_currency_id
               JOIN currencies tc ON tc.id = er.to_currency_id
               WHERE er.business_id = ? ORDER BY er.rate_date DESC, er.id DESC""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def convert_amount(business_id: int, amount: float, from_currency_id: int, to_currency_id: int, rate_date: str | None = None) -> dict[str, Any]:
    with get_db() as conn:
        _require_business(conn, business_id)
        if from_currency_id == to_currency_id:
            return {"amount": round(amount, 2), "rate": 1.0, "from_currency_id": from_currency_id, "to_currency_id": to_currency_id}
        if rate_date:
            row = conn.execute(
                "SELECT rate FROM exchange_rates WHERE business_id = ? AND from_currency_id = ? AND to_currency_id = ? AND rate_date <= ? ORDER BY rate_date DESC LIMIT 1",
                (business_id, from_currency_id, to_currency_id, rate_date),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT rate FROM exchange_rates WHERE business_id = ? AND from_currency_id = ? AND to_currency_id = ? ORDER BY rate_date DESC LIMIT 1",
                (business_id, from_currency_id, to_currency_id),
            ).fetchone()
        if row is None:
            raise ValueError("No exchange rate found for this currency pair")
        converted = round(amount * row["rate"], 2)
        return {"amount": converted, "rate": row["rate"], "from_currency_id": from_currency_id, "to_currency_id": to_currency_id}
