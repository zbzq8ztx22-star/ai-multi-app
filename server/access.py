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

import math
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
    "employee_id": "employees",
    "payslip_id": "payslips",
    "pay_period_id": "pay_periods",
}

# Blueprint-specific meanings for a field already mapped globally. Payroll
# calls its pay-period identifier ``period_id`` in paths, query args and
# bodies, which elsewhere means a closing_periods id.
FIELD_TO_TABLE_OVERRIDES = {
    "payroll": {"period_id": "pay_periods"},
}


def _table_for_field(key: str) -> str | None:
    override = FIELD_TO_TABLE_OVERRIDES.get(request.blueprint or "")
    if override is not None and key in override:
        return override[key]
    return FIELD_TO_TABLE.get(key)


def _mapped_fields() -> set[str]:
    override = FIELD_TO_TABLE_OVERRIDES.get(request.blueprint or "")
    return set(FIELD_TO_TABLE) | set(override or {})


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
    "payslips": (
        "SELECT e.business_id FROM payslips p"
        " JOIN employees e ON e.id = p.employee_id WHERE p.id = ?"
    ),
}


def normalize_id(value: Any) -> int | None:
    """Return the integer a service would act on for this identifier, or None.

    Authorization must see every representation the service layer accepts:
    services coerce ids with ``int(...)`` (ints, floats, decimal strings with
    optional sign/whitespace/underscores), and SQLite's numeric affinity
    additionally matches well-formed real literals such as ``"2.0"``. Booleans
    and non-numeric values are rejected.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                number = float(text)
            except ValueError:
                return None
            return int(number) if math.isfinite(number) else None
    return None


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


def _assert_not_last_owner(
    conn: sqlite3.Connection, user_id: int, business_id: int
) -> None:
    """Raise when removing or downgrading this user would orphan the business."""
    current = conn.execute(
        "SELECT role FROM user_business_access WHERE user_id = ? AND business_id = ?",
        (user_id, business_id),
    ).fetchone()
    if current is None or current["role"] != "owner":
        return
    owners = conn.execute(
        "SELECT COUNT(*) AS n FROM user_business_access"
        " WHERE business_id = ? AND role = 'owner'",
        (business_id,),
    ).fetchone()["n"]
    if owners <= 1:
        raise ValueError("Cannot remove or downgrade the last owner")


def solely_owned_businesses(conn: sqlite3.Connection, user_id: int) -> list[int]:
    """Businesses where this user is the only owner."""
    rows = conn.execute(
        "SELECT uba.business_id FROM user_business_access uba"
        " WHERE uba.user_id = ? AND uba.role = 'owner'"
        " AND NOT EXISTS ("
        " SELECT 1 FROM user_business_access other"
        " WHERE other.business_id = uba.business_id AND other.role = 'owner'"
        " AND other.user_id != uba.user_id"
        " )",
        (user_id,),
    ).fetchall()
    return [row["business_id"] for row in rows]


def grant_access(user_id: int, business_id: int, role: str) -> None:
    if role not in BUSINESS_ROLES:
        raise ValueError("Invalid role")
    now = now_utc()
    with get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM users WHERE id = ?", (user_id,)
        ).fetchone() is None:
            raise ValueError("User not found")
        if conn.execute(
            "SELECT 1 FROM businesses WHERE id = ?", (business_id,)
        ).fetchone() is None:
            raise ValueError("Business not found")
        if role != "owner":
            _assert_not_last_owner(conn, user_id, business_id)
        conn.execute(
            "INSERT INTO user_business_access (user_id, business_id, role, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id, business_id) DO UPDATE SET role = excluded.role, updated_at = excluded.updated_at",
            (user_id, business_id, role, now, now),
        )
        conn.commit()


def revoke_access(user_id: int, business_id: int) -> None:
    with get_db() as conn:
        current = conn.execute(
            "SELECT role FROM user_business_access WHERE user_id = ? AND business_id = ?",
            (user_id, business_id),
        ).fetchone()
        if current is None:
            raise ValueError("Access grant not found")
        _assert_not_last_owner(conn, user_id, business_id)
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


def _collect_body_refs(
    value: Any, out: list[tuple[str, int]], invalid: list[str]
) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            table = _table_for_field(key)
            if table is not None:
                if item is None:
                    continue
                record_id = normalize_id(item)
                if record_id is None:
                    invalid.append(key)
                else:
                    out.append((table, record_id))
            elif isinstance(item, (dict, list)):
                _collect_body_refs(item, out, invalid)
    elif isinstance(value, list):
        for item in value:
            _collect_body_refs(item, out, invalid)


def tenant_guard() -> Any:
    """before_request hook enforcing tenant isolation on a blueprint."""
    user_id = session.get("user_id")
    if user_id is None or request.method == "OPTIONS":
        # Unauthenticated requests are answered by the view's own decorators;
        # OPTIONS preflights carry no cookies.
        return None

    # The payroll assistant is read-only despite being a POST endpoint.
    min_role = (
        "viewer"
        if request.method in ("GET", "HEAD")
        or request.endpoint == "payroll.payroll_assistant"
        else "editor"
    )

    refs: list[tuple[str, int]] = []
    invalid: list[str] = []
    for key, value in (request.view_args or {}).items():
        table = _table_for_field(key)
        if table is not None:
            record_id = normalize_id(value)
            if record_id is None:
                invalid.append(key)
            else:
                refs.append((table, record_id))
    for key in _mapped_fields():
        raw = request.args.get(key)
        if raw is not None:
            record_id = normalize_id(raw)
            if record_id is None:
                invalid.append(key)
            else:
                refs.append((_table_for_field(key), record_id))
    if request.is_json:
        _collect_body_refs(request.get_json(silent=True), refs, invalid)

    # A known resource-reference field carrying a value no service could use
    # as an id is rejected outright rather than silently skipped.
    if invalid:
        return jsonify({"error": f"Invalid identifier: {sorted(set(invalid))[0]}"}), 400

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
