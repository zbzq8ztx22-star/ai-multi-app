from __future__ import annotations

import sqlite3
from typing import Any

from payroll.db import get_db, now_utc, row_to_dict

FORMAT_VERSION = 2
SUPPORTED_VERSIONS = {1, 2}

# Structural limits applied before any row is written.
MAX_TABLES = 64
MAX_ROWS_PER_TABLE = 100_000
MAX_TOTAL_ROWS = 500_000

# The complete business-owned data graph, ordered so every foreign key is
# remapped only after its parent table has been imported.
#
# Scope "business"     -> exported with WHERE business_id = ?
# Scope (col, parent)  -> exported via the already-exported parent ids
_TABLE_GRAPH: list[tuple[str, Any]] = [
    ("account_groups", "business"),
    ("accounts", "business"),
    ("accounting_contacts", "business"),
    ("cost_centers", "business"),
    ("depreciation_assets", "business"),
    ("journal_entries", "business"),
    ("journal_lines", ("entry_id", "journal_entries")),
    ("invoices", "business"),
    ("invoice_payments", ("invoice_id", "invoices")),
    ("expenses", "business"),
    ("budgets", "business"),
    ("reconciliations", "business"),
    ("recurring_expenses", "business"),
    ("currencies", "business"),
    ("exchange_rates", "business"),
    ("closing_periods", "business"),
    ("tax_payments", "business"),
    ("payment_terms", "business"),
    ("credit_notes", "business"),
    ("inventory_items", "business"),
    ("inventory_movements", "business"),
    ("projects", "business"),
    ("bank_transactions", "business"),
    ("sales_tax_rates", "business"),
    ("purchase_orders", "business"),
    ("purchase_order_lines", ("po_id", "purchase_orders")),
    ("employees", "business"),
    ("pay_periods", "business"),
    ("payslips", ("employee_id", "employees")),
    ("payslip_deductions", ("payslip_id", "payslips")),
    ("employee_ytd", ("employee_id", "employees")),
    ("taxpayers", "taxpayers"),
    ("business_owners", "business"),
    ("tax_returns", ("taxpayer_id", "taxpayers")),
]

# Foreign-key columns remapped to the ids created during import. Nullable
# FKs keep NULL; a non-null value with no mapped counterpart aborts the
# whole import.
_FK_REMAPS: dict[str, dict[str, str]] = {
    "accounts": {"group_id": "account_groups"},
    "depreciation_assets": {
        "asset_account_id": "accounts",
        "accumulated_account_id": "accounts",
        "depreciation_account_id": "accounts",
    },
    "journal_entries": {"depreciation_asset_id": "depreciation_assets"},
    "journal_lines": {
        "entry_id": "journal_entries",
        "account_id": "accounts",
        "cost_center_id": "cost_centers",
    },
    "invoices": {
        "customer_id": "accounting_contacts",
        "receivable_account_id": "accounts",
        "revenue_account_id": "accounts",
        "journal_entry_id": "journal_entries",
    },
    "invoice_payments": {
        "invoice_id": "invoices",
        "cash_account_id": "accounts",
        "journal_entry_id": "journal_entries",
    },
    "expenses": {
        "vendor_id": "accounting_contacts",
        "expense_account_id": "accounts",
        "payment_account_id": "accounts",
        "journal_entry_id": "journal_entries",
    },
    "budgets": {"account_id": "accounts"},
    "reconciliations": {"account_id": "accounts"},
    "recurring_expenses": {
        "vendor_id": "accounting_contacts",
        "expense_account_id": "accounts",
        "payment_account_id": "accounts",
    },
    "exchange_rates": {
        "from_currency_id": "currencies",
        "to_currency_id": "currencies",
    },
    "credit_notes": {
        "invoice_id": "invoices",
        "customer_id": "accounting_contacts",
        "receivable_account_id": "accounts",
        "revenue_account_id": "accounts",
        "journal_entry_id": "journal_entries",
    },
    "inventory_items": {
        "inventory_account_id": "accounts",
        "cogs_account_id": "accounts",
        "sales_account_id": "accounts",
    },
    "inventory_movements": {"item_id": "inventory_items"},
    "projects": {
        "customer_id": "accounting_contacts",
        "cost_center_id": "cost_centers",
    },
    "bank_transactions": {
        "account_id": "accounts",
        "matched_journal_line_id": "journal_lines",
    },
    "sales_tax_rates": {"tax_account_id": "accounts"},
    "purchase_orders": {
        "vendor_id": "accounting_contacts",
        "expense_account_id": "accounts",
        "payment_account_id": "accounts",
        "journal_entry_id": "journal_entries",
    },
    "purchase_order_lines": {"po_id": "purchase_orders"},
    "payslips": {"employee_id": "employees", "period_id": "pay_periods"},
    "payslip_deductions": {"payslip_id": "payslips"},
    "employee_ytd": {"employee_id": "employees"},
    "taxpayers": {"employee_id": "employees"},
    "business_owners": {"taxpayer_id": "taxpayers"},
    "tax_returns": {"taxpayer_id": "taxpayers"},
}

# FKs that are detached (set to NULL) instead of aborting the import when
# they point outside the exported business: a business owner may be linked
# to an employee that belongs to a different business.
_DETACHABLE_FKS: set[tuple[str, str]] = {("taxpayers", "employee_id")}


def export_business(business_id: int) -> dict[str, Any]:
    """Export all data for a single business as a JSON-serializable dict."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if row is None:
            raise ValueError("Business not found")
        data: dict[str, Any] = {
            "format_version": FORMAT_VERSION,
            "business": row_to_dict(row),
            "tables": {},
        }
        tables = data["tables"]
        for table, scope in _TABLE_GRAPH:
            if scope == "business":
                rows = conn.execute(f"SELECT * FROM {table} WHERE business_id = ?", (business_id,)).fetchall()
            elif scope == "taxpayers":
                # Taxpayers are scoped indirectly through business_owners and
                # through payroll employees.
                rows = conn.execute(
                    """SELECT * FROM taxpayers
                       WHERE employee_id IN (SELECT id FROM employees WHERE business_id = ?)
                          OR id IN (SELECT taxpayer_id FROM business_owners WHERE business_id = ?)""",
                    (business_id, business_id),
                ).fetchall()
            else:
                fk_col, parent_table = scope
                parent_ids = [r["id"] for r in tables[parent_table]]
                if not parent_ids:
                    rows = []
                else:
                    placeholders = ",".join("?" * len(parent_ids))
                    rows = conn.execute(f"SELECT * FROM {table} WHERE {fk_col} IN ({placeholders})", parent_ids).fetchall()
            tables[table] = [row_to_dict(r) for r in rows]
        data["exported_at"] = conn.execute("SELECT datetime('now') AS now").fetchone()["now"]
    return data


def _validate_backup(data: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate backup shape, version and structural limits before import."""
    if not isinstance(data, dict):
        raise ValueError("Invalid backup format")
    business = data.get("business")
    tables = data.get("tables")
    if not isinstance(business, dict) or not isinstance(tables, dict):
        raise ValueError("Invalid backup format")
    version = data.get("format_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported backup format version: {version}")
    if len(tables) > MAX_TABLES:
        raise ValueError("Backup has too many tables")
    source_business_id = business.get("id")
    scoped_tables = {table for table, scope in _TABLE_GRAPH if scope == "business"}
    total_rows = 0
    for name, rows in tables.items():
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            raise ValueError(f"Invalid rows for table {name}")
        if len(rows) > MAX_ROWS_PER_TABLE:
            raise ValueError(f"Table {name} exceeds the row limit")
        if name in scoped_tables and isinstance(source_business_id, int):
            if any(r.get("business_id") != source_business_id for r in rows):
                raise ValueError(f"Table {name} contains rows from another business")
        total_rows += len(rows)
    if total_rows > MAX_TOTAL_ROWS:
        raise ValueError("Backup exceeds the total row limit")
    return business, tables


def _table_columns(conn: sqlite3.Connection) -> dict[str, set[str]]:
    return {
        table: {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for table, _ in _TABLE_GRAPH
    }


def import_business(data: dict[str, Any]) -> dict[str, Any]:
    """Import business data from a backup dict. Creates a new business.

    Everything runs in a single transaction: any failure leaves the
    database untouched.
    """
    business_data, tables = _validate_backup(data)
    now = now_utc()
    with get_db() as conn:
        columns = _table_columns(conn)
        cursor = conn.execute(
            "INSERT INTO businesses (legal_name, dba_name, entity_type, ein_last4, formation_state, fiscal_year_end, accounting_method, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (business_data.get("legal_name", f"Imported {now}"), business_data.get("dba_name", ""), business_data.get("entity_type", "llc"), business_data.get("ein_last4", ""), business_data.get("formation_state", ""), business_data.get("fiscal_year_end", "12-31"), business_data.get("accounting_method", "cash"), now, now),
        )
        new_business_id = cursor.lastrowid
        id_maps: dict[str, dict[int, int]] = {}
        imported: dict[str, int] = {}
        for table, _ in _TABLE_GRAPH:
            rows = tables.get(table, [])
            id_map: dict[int, int] = {}
            fks = _FK_REMAPS.get(table, {})
            valid_cols = columns[table]
            for row in rows:
                values: dict[str, Any] = {}
                for key, value in row.items():
                    if key == "id" or key not in valid_cols:
                        continue
                    values[key] = value
                if "business_id" in valid_cols:
                    values["business_id"] = new_business_id
                for column, parent in fks.items():
                    old_value = values.get(column)
                    if old_value is None:
                        continue
                    new_value = id_maps.get(parent, {}).get(old_value)
                    if new_value is None:
                        if (table, column) in _DETACHABLE_FKS:
                            values[column] = None
                            continue
                        raise ValueError(f"Unresolved reference: {table}.{column} -> {parent}({old_value})")
                    values[column] = new_value
                cols = ", ".join(values)
                marks = ", ".join("?" * len(values))
                cursor = conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(values.values()))
                if "id" in row and "id" in valid_cols:
                    id_map[row["id"]] = cursor.lastrowid
            id_maps[table] = id_map
            imported[table] = len(rows)
        conn.commit()
        return {
            "business_id": new_business_id,
            "business_name": business_data.get("legal_name", "Imported"),
            "imported_rows": imported,
        }
