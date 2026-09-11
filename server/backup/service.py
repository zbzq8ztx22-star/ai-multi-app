from __future__ import annotations

from typing import Any

from payroll.db import get_db, row_to_dict


EXPORT_TABLES = [
    "accounts",
    "journal_entries",
    "accounting_contacts",
    "invoices",
    "expenses",
    "budgets",
    "reconciliations",
    "recurring_expenses",
]

# Tables that don't have business_id directly - exported via parent tables
CHILD_TABLES = {
    "journal_lines": ("entry_id", "journal_entries"),
    "invoice_payments": ("invoice_id", "invoices"),
}


def export_business(business_id: int) -> dict[str, Any]:
    """Export all data for a single business as a JSON-serializable dict."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if row is None:
            raise ValueError("Business not found")
        data: dict[str, Any] = {"business": row_to_dict(row), "tables": {}}
        # Business-level tables (have business_id column)
        for table in EXPORT_TABLES:
            rows = conn.execute(f"SELECT * FROM {table} WHERE business_id = ?", (business_id,)).fetchall()
            data["tables"][table] = [row_to_dict(r) for r in rows]
        # Child tables (linked via parent IDs)
        for child_table, (fk_col, parent_table) in CHILD_TABLES.items():
            parent_ids = [r["id"] for r in data["tables"][parent_table]]
            if parent_ids:
                placeholders = ",".join("?" * len(parent_ids))
                rows = conn.execute(f"SELECT * FROM {child_table} WHERE {fk_col} IN ({placeholders})", parent_ids).fetchall()
                data["tables"][child_table] = [row_to_dict(r) for r in rows]
            else:
                data["tables"][child_table] = []
        # Payroll and tax modules are not business-scoped in the current schema,
        # so we only export accounting data.
        data["exported_at"] = conn.execute("SELECT datetime('now') AS now").fetchone()["now"]
    return data


def import_business(data: dict[str, Any]) -> dict[str, Any]:
    """Import business data from a backup dict. Creates a new business."""
    if not isinstance(data, dict) or "business" not in data or "tables" not in data:
        raise ValueError("Invalid backup format")
    business_data = data["business"]
    tables = data["tables"]
    now = conn_now()
    with get_db() as conn:
        # Create new business
        cursor = conn.execute(
            "INSERT INTO businesses (legal_name, dba_name, entity_type, ein_last4, formation_state, fiscal_year_end, accounting_method, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (business_data.get("legal_name", f"Imported {now}"), business_data.get("dba_name", ""), business_data.get("entity_type", "llc"), business_data.get("ein_last4", ""), business_data.get("formation_state", ""), business_data.get("fiscal_year_end", "12-31"), business_data.get("accounting_method", "cash"), now, now),
        )
        new_business_id = cursor.lastrowid
        # Map old IDs to new IDs
        account_map: dict[int, int] = {}
        contact_map: dict[int, int] = {}
        # Import accounts
        for acct in tables.get("accounts", []):
            old_id = acct["id"]
            cursor = conn.execute(
                "INSERT INTO accounts (business_id, code, name, account_type, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_business_id, acct["code"], acct["name"], acct["account_type"], acct.get("active", 1), now, now),
            )
            account_map[old_id] = cursor.lastrowid
        # Import contacts
        for contact in tables.get("accounting_contacts", []):
            old_id = contact["id"]
            cursor = conn.execute(
                "INSERT INTO accounting_contacts (business_id, name, email, contact_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_business_id, contact["name"], contact.get("email"), contact.get("contact_type", "customer"), now, now),
            )
            contact_map[old_id] = cursor.lastrowid
        # Import journal entries and lines
        entry_map: dict[int, int] = {}
        for entry in tables.get("journal_entries", []):
            old_id = entry["id"]
            cursor = conn.execute(
                "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (new_business_id, entry["entry_date"], entry.get("reference", ""), entry.get("description", ""), entry.get("status", "draft"), now, now),
            )
            entry_map[old_id] = cursor.lastrowid
        for line in tables.get("journal_lines", []):
            new_entry_id = entry_map.get(line["entry_id"])
            new_account_id = account_map.get(line["account_id"])
            if new_entry_id and new_account_id:
                conn.execute(
                    "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, ?, ?, ?)",
                    (new_entry_id, new_account_id, line.get("description", ""), line.get("debit", 0), line.get("credit", 0)),
                )
        conn.commit()
        return {"business_id": new_business_id, "business_name": business_data.get("legal_name", "Imported")}


def conn_now() -> str:
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
