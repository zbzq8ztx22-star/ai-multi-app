from __future__ import annotations

from typing import Any

from payroll.db import get_db, now_utc, row_to_dict


def log(action: str, module: str, user: dict[str, Any] | None, entity_type: str = "", entity_id: int | None = None, description: str = "") -> None:
    """Insert an audit log entry. Safe to call from any module."""
    user_id = user.get("id") if user else None
    username = user.get("username", "") if user else ""
    with get_db() as conn:
        conn.execute(
            "INSERT INTO audit_log (user_id, username, action, module, entity_type, entity_id, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, action, module, entity_type, entity_id, description, now_utc()),
        )
        conn.commit()


def list_entries(module: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    query = "SELECT * FROM audit_log"
    params: list[Any] = []
    if module:
        query += " WHERE module = ?"
        params.append(module)
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(min(max(limit, 1), 500))
    with get_db() as conn:
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]
