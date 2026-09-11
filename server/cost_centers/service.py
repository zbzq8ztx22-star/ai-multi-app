from __future__ import annotations

from typing import Any

from payroll.db import get_db, now_utc, row_to_dict


def _require_business(conn, business_id: int) -> None:
    row = conn.execute("SELECT id FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if row is None:
        raise ValueError("Business not found")


def list_cost_centers(business_id: int, active_only: bool = False) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = "SELECT * FROM cost_centers WHERE business_id = ?"
        params: list[Any] = [business_id]
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY code"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_cost_center(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    if not code or not name:
        raise ValueError("code and name are required")
    description = str(data.get("description", "")).strip()
    active = 1 if data.get("active", True) else 0
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        try:
            cursor = conn.execute(
                "INSERT INTO cost_centers (business_id, code, name, description, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (business_id, code, name, description, active, now, now),
            )
        except Exception:
            raise ValueError("Cost center code already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM cost_centers WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_cost_center(cost_center_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM cost_centers WHERE id = ?", (cost_center_id,)).fetchone()
        if row is None:
            raise ValueError("Cost center not found")
        updates: list[str] = []
        params: list[Any] = []
        for field in ("code", "name", "description"):
            val = data.get(field)
            if val is not None:
                updates.append(f"{field} = ?")
                params.append(str(val).strip())
        if "active" in data:
            updates.append("active = ?")
            params.append(1 if data["active"] else 0)
        if updates:
            updates.append("updated_at = ?")
            params.append(now_utc())
            conn.execute(f"UPDATE cost_centers SET {', '.join(updates)} WHERE id = ?", [*params, cost_center_id])
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM cost_centers WHERE id = ?", (cost_center_id,)).fetchone())


def delete_cost_center(cost_center_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM cost_centers WHERE id = ?", (cost_center_id,)).fetchone()
        if row is None:
            raise ValueError("Cost center not found")
        conn.execute("UPDATE journal_lines SET cost_center_id = NULL WHERE cost_center_id = ?", (cost_center_id,))
        conn.execute("DELETE FROM cost_centers WHERE id = ?", (cost_center_id,))
        conn.commit()


def cost_center_summary(business_id: int, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
    """Summarize expenses by cost center."""
    with get_db() as conn:
        _require_business(conn, business_id)
        query = """SELECT cc.id, cc.code, cc.name,
                   COALESCE(SUM(jl.debit - jl.credit), 0) AS total_expenses,
                   COUNT(DISTINCT je.id) AS entry_count
                   FROM cost_centers cc
                   LEFT JOIN journal_lines jl ON jl.cost_center_id = cc.id
                   LEFT JOIN journal_entries je ON je.id = jl.entry_id AND je.business_id = cc.business_id AND je.status = 'posted'
                   LEFT JOIN accounts a ON a.id = jl.account_id AND a.account_type = 'expense'
                   WHERE cc.business_id = ?"""
        params: list[Any] = [business_id]
        if start_date:
            query += " AND je.entry_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND je.entry_date <= ?"
            params.append(end_date)
        query += " GROUP BY cc.id, cc.code, cc.name ORDER BY cc.code"
        rows = conn.execute(query, params).fetchall()
        return [row_to_dict(row) for row in rows]
