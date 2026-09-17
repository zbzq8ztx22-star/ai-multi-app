from __future__ import annotations

from typing import Any

from payroll.db import get_db, now_utc, row_to_dict

TAXPAYER_TYPES = {"individual", "business"}
FILING_STATUSES = {"single", "married_joint", "married_separate", "hoh", "widow", "business"}
ENTITY_TYPES = {"sole_proprietorship", "llc", "partnership", "s_corp", "c_corp", "nonprofit"}
ACCOUNTING_METHODS = {"cash", "accrual"}


def _text(data: dict[str, Any], field: str, required: bool = False) -> str:
    value = data.get(field, "")
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if required and not value:
        raise ValueError(f"{field} is required")
    return value


def _last4(data: dict[str, Any], field: str) -> str:
    value = _text(data, field)
    if value and (len(value) != 4 or not value.isdigit()):
        raise ValueError(f"{field} must contain exactly four digits")
    return value


def list_taxpayers() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM taxpayers ORDER BY legal_name, id").fetchall()
        return [row_to_dict(row) for row in rows]


def create_taxpayer(data: dict[str, Any]) -> dict[str, Any]:
    taxpayer_type = data.get("taxpayer_type", "individual")
    filing_status = data.get("filing_status", "single")
    if taxpayer_type not in TAXPAYER_TYPES:
        raise ValueError("Invalid taxpayer_type")
    if filing_status not in FILING_STATUSES:
        raise ValueError("Invalid filing_status")
    employee_id = data.get("employee_id") or None
    now = now_utc()
    values = (
        employee_id,
        _text(data, "legal_name", True),
        taxpayer_type,
        filing_status,
        _text(data, "residence_state"),
        _last4(data, "identifier_last4"),
        _text(data, "email"),
        _text(data, "phone"),
        _text(data, "address"),
        now,
        now,
    )
    with get_db() as conn:
        if employee_id and conn.execute("SELECT id FROM employees WHERE id = ?", (employee_id,)).fetchone() is None:
            raise ValueError("Employee not found")
        cursor = conn.execute(
            """INSERT INTO taxpayers
            (employee_id, legal_name, taxpayer_type, filing_status, residence_state,
             identifier_last4, email, phone, address, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            values,
        )
        conn.commit()
        row = conn.execute("SELECT * FROM taxpayers WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return row_to_dict(row)


def list_businesses(user_id: int | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        if user_id is None:
            rows = conn.execute("SELECT * FROM businesses ORDER BY legal_name, id").fetchall()
        else:
            rows = conn.execute(
                "SELECT b.* FROM businesses b"
                " JOIN user_business_access uba ON uba.business_id = b.id"
                " WHERE uba.user_id = ? ORDER BY b.legal_name, b.id",
                (user_id,),
            ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_business(data: dict[str, Any]) -> dict[str, Any]:
    entity_type = data.get("entity_type", "llc")
    accounting_method = data.get("accounting_method", "cash")
    if entity_type not in ENTITY_TYPES:
        raise ValueError("Invalid entity_type")
    if accounting_method not in ACCOUNTING_METHODS:
        raise ValueError("Invalid accounting_method")
    fiscal_year_end = _text(data, "fiscal_year_end") or "12-31"
    if len(fiscal_year_end) != 5 or fiscal_year_end[2] != "-":
        raise ValueError("fiscal_year_end must use MM-DD format")
    now = now_utc()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO businesses
            (legal_name, dba_name, entity_type, ein_last4, formation_state,
             fiscal_year_end, accounting_method, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _text(data, "legal_name", True),
                _text(data, "dba_name"),
                entity_type,
                _last4(data, "ein_last4"),
                _text(data, "formation_state"),
                fiscal_year_end,
                accounting_method,
                now,
                now,
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM businesses WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return row_to_dict(row)
