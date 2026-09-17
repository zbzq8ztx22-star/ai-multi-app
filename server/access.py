"""Business-level (tenant) authorization.

``users.role`` (admin/viewer) governs global concerns such as user
management. Business data is governed separately by ``user_business_access``:
every request touching business-scoped resources must resolve to a business
the logged-in user can access, at the required role level.

Denials never leak another tenant's data:

- resource or business exists but the user has no access -> 404 (indistinguishable
  from "does not exist" for record endpoints);
- user has access but an insufficient role -> 403.

``tenant_guard`` is registered with ``bp.before_request`` on every
business-scoped blueprint. It inspects path parameters, query arguments and
the JSON body (recursively) for known resource-reference fields, resolves each
to its owning business and requires the caller to hold at least the needed
role on every business referenced. Cross-tenant *consistency* (e.g. an entry
in business A whose lines point at business B's accounts, where the user can
access both) remains the service layer's job, unchanged.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from flask import jsonify, request, session

from payroll.db import get_db, now_utc

# Ordered so index comparison gives "at least this role".
BUSINESS_ROLES = ("viewer", "editor", "owner")


# Request fields that reference business-scoped resources. Keys may appear as
# path params, query args or JSON body fields (at any nesting depth).
FIELD_TO_TABLE = {
    "business_id": "businesses",
    "account_id": "accounts",
    "expense_account_id": "accounts",
    "payment_account_id": "accounts",
    "receivable_account_id": "accounts",
    "revenue_account_id": "accounts",
    "cash_account_id": "accounts",
    "gain_loss_account_id": "accounts",
    "inventory_account_id": "accounts",
    "cogs_account_id": "accounts",
    "sales_account_id": "accounts",
    "tax_account_id": "accounts",
    "asset_account_id": "accounts",
    "accumulated_account_id": "accounts",
    "depreciation_account_id": "accounts",
    "customer_id": "accounting_contacts",
    "vendor_id": "accounting_contacts",
    "contact_id": "accounting_contacts",
    "invoice_id": "invoices",
    "expense_id": "expenses",
    "budget_id": "budgets",
    "reconciliation_id": "reconciliations",
    "recurring_id": "recurring_expenses",
    "group_id": "account_groups",
    "cost_center_id": "cost_centers",
    "term_id": "payment_terms",
    "credit_id": "credit_notes",
    "asset_id": "depreciation_assets",
    "item_id": "inventory_items",
    "project_id": "projects",
    "tx_id": "bank_transactions",
    "rate_id": "sales_tax_rates",
    "po_id": "purchase_orders",
    "payment_id": "tax_payments",
    "period_id": "closing_periods",
    "entry_id": "journal_entries",
    "journal_entry_id": "journal_entries",
    "journal_line_id": "journal_lines",
    "from_currency_id": "currencies",
    "to_currency_id": "currencies",
}

# Tables whose business_id lives on a parent row.
_INDIRECT_BUSINESS_SQL = {
    "journal_lines": (
        "SELECT je.business_id FROM journal_lines jl"
        " JOIN journal_entries je ON je.id = jl.entry_id WHERE jl.id = ?"
    ),
    "invoice_payments": (
        "SELECT i.business_id FROM invoice_payments ip"
        " JOIN invoices i ON i.id = ip.invoice_id WHERE ip.id = ?"
    ),
    "purchase_order_lines": (
        "SELECT po.business_id FROM purchase_order_lines pol"
        " JOIN purchase_orders po ON po.id = pol.po_id WHERE pol.id = ?"
    ),
    "inventory_movements": (
        "SELECT i.business_id FROM inventory_movements m"
        " JOIN inventory_items i ON i.id = m.item_id WHERE m.id = ?"
    ),
}


def business_id_of(conn: sqlite3.Connection, table: str, record_id: int) -> int | None:
    """Return the owning business_id for a record, or None if it doesn't exist."""
    if table == "businesses":
        row = conn.execute(
            "SELECT id FROM businesses WHERE id = ?", (record_id,)
        ).fetchone()
        return row["id"] if row else None
    sql = _INDIRECT_BUSINESS_SQL.get(
        table, f"SELECT business_id FROM {table} WHERE id = ?"
    )
    row = conn.execute(sql, (record_id,)).fetchone()
    return row["business_id"] if row else None


def get_role(user_id: int, business_id: int) -> str | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT role FROM user_business_access WHERE user_id = ? AND business_id = ?",
            (user_id, business_id),
        ).fetchone()
        return row["role"] if row else None


def has_access(user_id: int, business_id: int, min_role: str = "viewer") -> bool:
    role = get_role(user_id, business_id)
    if role is None:
        return False
    return BUSINESS_ROLES.index(role) >= BUSINESS_ROLES.index(min_role)


def accessible_business_ids(user_id: int) -> list[int]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT business_id FROM user_business_access WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return [row["business_id"] for row in rows]


def grant_access(user_id: int, business_id: int, role: str) -> None:
    if role not in BUSINESS_ROLES:
        raise ValueError("Invalid role")
    now = now_utc()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_business_access (user_id, business_id, role, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id, business_id) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at",
            (user_id, business_id, role, now, now),
        )
        conn.commit()


def revoke_access(user_id: int, business_id: int) -> None:
    with get_db() as conn:
        owner_count = conn.execute(
            "SELECT COUNT(*) AS n FROM user_business_access"
            " WHERE business_id = ? AND role = 'owner'",
            (business_id,),
        ).fetchone()["n"]
        current = conn.execute(
            "SELECT role FROM user_business_access WHERE user_id = ? AND business_id = ?",
            (user_id, business_id),
        ).fetchone()
        if current is None:
            raise ValueError("Access grant not found")
        if current["role"] == "owner" and owner_count <= 1:
            raise ValueError("Cannot revoke the last owner")
        conn.execute(
            "DELETE FROM user_business_access WHERE user_id = ? AND business_id = ?",
            (user_id, business_id),
        )
        conn.commit()


def list_grants(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT uba.user_id, u.username, uba.role, uba.created_at, uba.updated_at"
            " FROM user_business_access uba JOIN users u ON u.id = uba.user_id"
            " WHERE uba.business_id = ? ORDER BY u.username",
            (business_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def _not_found() -> Any:
    return jsonify({"error": "Not found"}), 404


def _forbidden() -> Any:
    return jsonify({"error": "Forbidden"}), 403


def _check_access(user_id: int, business_id: int, min_role: str) -> Any:
    role = get_role(user_id, business_id)
    if role is None:
        return _not_found()
    if BUSINESS_ROLES.index(role) < BUSINESS_ROLES.index(min_role):
        return _forbidden()
    return None


def require_business_access(business_id: int, min_role: str = "viewer") -> Any:
    """Route-level check for endpoints that already know the business_id."""
    user_id = session.get("user_id")
    if user_id is None:
        return jsonify({"error": "Unauthorized"}), 401
    return _check_access(user_id, business_id, min_role)


def _collect_body_refs(value: Any, out: list[tuple[str, int]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            table = FIELD_TO_TABLE.get(key)
            if table is not None and isinstance(item, int) and not isinstance(item, bool):
                out.append((table, item))
            elif isinstance(item, (dict, list)):
                _collect_body_refs(item, out)
    elif isinstance(value, list):
        for item in value:
            _collect_body_refs(item, out)


def tenant_guard() -> Any:
    """before_request hook enforcing tenant isolation on a blueprint."""
    user_id = session.get("user_id")
    if user_id is None or request.method == "OPTIONS":
        # Unauthenticated requests are answered by the view's own decorators;
        # OPTIONS preflights carry no cookies.
        return None

    min_role = "viewer" if request.method in ("GET", "HEAD") else "editor"

    refs: list[tuple[str, int]] = []
    for key, value in (request.view_args or {}).items():
        table = FIELD_TO_TABLE.get(key)
        if table is not None and isinstance(value, int):
            refs.append((table, value))
    for key, table in FIELD_TO_TABLE.items():
        value = request.args.get(key, type=int)
        if value is not None:
            refs.append((table, value))
    if request.is_json:
        _collect_body_refs(request.get_json(silent=True), refs)

    business_ids: set[int] = set()
    with get_db() as conn:
        for table, record_id in refs:
            bid = business_id_of(conn, table, record_id)
            if bid is not None:
                business_ids.add(bid)

    for business_id in business_ids:
        denied = _check_access(user_id, business_id, min_role)
        if denied is not None:
            return denied
    return None
