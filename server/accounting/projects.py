from __future__ import annotations

import sqlite3
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _date, _require_business


def list_projects(business_id: int, status: str | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = """SELECT p.*, c.name AS customer_name, cc.code AS cost_center_code
                  FROM projects p
                  LEFT JOIN accounting_contacts c ON c.id = p.customer_id
                  LEFT JOIN cost_centers cc ON cc.id = p.cost_center_id
                  WHERE p.business_id = ?"""
        params: list[Any] = [business_id]
        if status:
            query += " AND p.status = ?"
            params.append(status)
        query += " ORDER BY p.start_date DESC, p.id DESC"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_project(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    code = str(data.get("code", "")).strip()
    name = str(data.get("name", "")).strip()
    if not code or not name:
        raise ValueError("code and name are required")
    description = str(data.get("description", "")).strip()
    customer_id = data.get("customer_id")
    start_date = _date(data.get("start_date"), "start_date")
    end_date = data.get("end_date")
    if end_date:
        end_date = _date(end_date, "end_date")
        if end_date < start_date:
            raise ValueError("end_date cannot be before start_date")
    budgeted_revenue = float(data.get("budgeted_revenue", 0))
    budgeted_cost = float(data.get("budgeted_cost", 0))
    if budgeted_revenue < 0 or budgeted_cost < 0:
        raise ValueError("budgeted_revenue and budgeted_cost must be >= 0")
    status = str(data.get("status", "active")).strip().lower()
    if status not in ("active", "completed", "on_hold", "cancelled"):
        raise ValueError("status must be one of: active, completed, on_hold, cancelled")
    cost_center_id = data.get("cost_center_id")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        if customer_id is not None:
            cust = conn.execute("SELECT id FROM accounting_contacts WHERE id = ? AND business_id = ?", (customer_id, business_id)).fetchone()
            if cust is None:
                raise ValueError("Customer not found for this business")
        if cost_center_id is not None:
            cc = conn.execute("SELECT id FROM cost_centers WHERE id = ? AND business_id = ?", (cost_center_id, business_id)).fetchone()
            if cc is None:
                raise ValueError("Cost center not found for this business")
        try:
            cursor = conn.execute(
                "INSERT INTO projects (business_id, code, name, description, customer_id, start_date, end_date, budgeted_revenue, budgeted_cost, status, cost_center_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (business_id, code, name, description, customer_id, start_date, end_date, budgeted_revenue, budgeted_cost, status, cost_center_id, now, now),
            )
        except sqlite3.IntegrityError:
            raise ValueError("Project code already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_project(project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ValueError("Project not found")
        updates: list[str] = []
        params: list[Any] = []
        for field in ("name", "description"):
            val = data.get(field)
            if val is not None:
                updates.append(f"{field} = ?")
                params.append(str(val).strip())
        for field in ("budgeted_revenue", "budgeted_cost"):
            val = data.get(field)
            if val is not None:
                val = float(val)
                if val < 0:
                    raise ValueError(f"{field} must be >= 0")
                updates.append(f"{field} = ?")
                params.append(val)
        if "end_date" in data:
            val = data.get("end_date")
            if val:
                val = _date(val, "end_date")
            updates.append("end_date = ?")
            params.append(val)
        if "status" in data:
            status = str(data["status"]).strip().lower()
            if status not in ("active", "completed", "on_hold", "cancelled"):
                raise ValueError("status must be one of: active, completed, on_hold, cancelled")
            updates.append("status = ?")
            params.append(status)
        if "customer_id" in data:
            updates.append("customer_id = ?")
            params.append(data["customer_id"])
        if updates:
            updates.append("updated_at = ?")
            params.append(now_utc())
            conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", [*params, project_id])
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone())


def delete_project(project_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ValueError("Project not found")
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()


def project_profitability(project_id: int) -> dict[str, Any]:
    """Calculate actual revenue and expenses for a project via its cost center."""
    with get_db() as conn:
        project = conn.execute(
            """SELECT p.*, c.name AS customer_name, cc.code AS cost_center_code
               FROM projects p
               LEFT JOIN accounting_contacts c ON c.id = p.customer_id
               LEFT JOIN cost_centers cc ON cc.id = p.cost_center_id
               WHERE p.id = ?""",
            (project_id,),
        ).fetchone()
        if project is None:
            raise ValueError("Project not found")
        project = row_to_dict(project)
        actual_revenue = 0.0
        actual_cost = 0.0
        if project["cost_center_id"]:
            # Get revenue entries linked to this cost center
            rev_rows = conn.execute(
                """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS total
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   JOIN accounts a ON a.id = jl.account_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND jl.cost_center_id = ? AND a.account_type = 'revenue'""",
                (project["business_id"], project["cost_center_id"]),
            ).fetchone()
            actual_revenue = round(rev_rows["total"], 2)
            # Get expense entries linked to this cost center
            exp_rows = conn.execute(
                """SELECT COALESCE(SUM(jl.debit - jl.credit), 0) AS total
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   JOIN accounts a ON a.id = jl.account_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND jl.cost_center_id = ? AND a.account_type = 'expense'""",
                (project["business_id"], project["cost_center_id"]),
            ).fetchone()
            actual_cost = round(exp_rows["total"], 2)
        actual_profit = round(actual_revenue - actual_cost, 2)
        budgeted_profit = round(project["budgeted_revenue"] - project["budgeted_cost"], 2)
        return {
            "project": project,
            "budgeted_revenue": project["budgeted_revenue"],
            "budgeted_cost": project["budgeted_cost"],
            "budgeted_profit": budgeted_profit,
            "actual_revenue": actual_revenue,
            "actual_cost": actual_cost,
            "actual_profit": actual_profit,
            "revenue_variance": round(actual_revenue - project["budgeted_revenue"], 2),
            "cost_variance": round(actual_cost - project["budgeted_cost"], 2),
            "profit_variance": round(actual_profit - budgeted_profit, 2),
            "profit_margin": round((actual_profit / actual_revenue) * 100, 2) if actual_revenue > 0 else None,
        }
