"""Versioned SQLite schema migrations.

``SCHEMA`` in ``db.py`` is the baseline used for clean installations and to
create tables that are missing entirely. This module holds the numbered,
idempotent migrations that upgrade *existing* tables — column renames, added
columns and the ``expenses`` rebuild that relaxes ``journal_entry_id``.

Each migration runs inside its own transaction and is recorded in
``schema_migrations``. Databases created before this system existed have no
``schema_migrations`` table, so every migration is applied; the guards below
(column/table existence checks) make replaying them harmless.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Callable, NamedTuple

MIGRATIONS_TABLE = "schema_migrations"


class Migration(NamedTuple):
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if table_exists(conn, table) and not column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _m001_employees_pay_frequency(conn: sqlite3.Connection) -> None:
    """Rename employees.salary_frequency to pay_frequency."""
    if not table_exists(conn, "employees"):
        return
    if column_exists(conn, "employees", "salary_frequency"):
        if not column_exists(conn, "employees", "pay_frequency"):
            conn.execute(
                "ALTER TABLE employees"
                " RENAME COLUMN salary_frequency TO pay_frequency"
            )
    elif not column_exists(conn, "employees", "pay_frequency"):
        conn.execute(
            "ALTER TABLE employees ADD COLUMN pay_frequency TEXT NOT NULL"
            " DEFAULT 'biweekly' CHECK(pay_frequency IN"
            " ('weekly', 'biweekly', 'semimonthly', 'monthly', 'annual'))"
        )


def _m002_employee_w4_fields(conn: sqlite3.Connection) -> None:
    add_column(conn, "employees", "dependents",
               "INTEGER NOT NULL DEFAULT 0 CHECK(dependents >= 0)")
    add_column(conn, "employees", "other_income",
               "REAL NOT NULL DEFAULT 0 CHECK(other_income >= 0)")
    add_column(conn, "employees", "w4_deductions",
               "REAL NOT NULL DEFAULT 0 CHECK(w4_deductions >= 0)")
    add_column(conn, "employees", "multiple_jobs",
               "INTEGER NOT NULL DEFAULT 0 CHECK(multiple_jobs IN (0, 1))")


def _m003_payslip_wage_bases(conn: sqlite3.Connection) -> None:
    for column in ("fica_wages", "medicare_wages"):
        add_column(conn, "payslips", column, "REAL NOT NULL DEFAULT 0")


def _m004_accounts_group_id(conn: sqlite3.Connection) -> None:
    add_column(
        conn, "accounts", "group_id",
        "INTEGER REFERENCES account_groups(id) ON DELETE SET NULL",
    )


def _m005_journal_lines_cost_center(conn: sqlite3.Connection) -> None:
    add_column(
        conn, "journal_lines", "cost_center_id",
        "INTEGER REFERENCES cost_centers(id) ON DELETE SET NULL",
    )


def _m006_contacts_1099_fields(conn: sqlite3.Connection) -> None:
    add_column(conn, "accounting_contacts", "tax_id", "TEXT NOT NULL DEFAULT ''")
    add_column(conn, "accounting_contacts", "is_1099",
               "INTEGER NOT NULL DEFAULT 0 CHECK(is_1099 IN (0, 1))")


_EXPENSES_REBUILD = """CREATE TABLE expenses_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    vendor_id INTEGER,
    expense_date TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    expense_account_id INTEGER NOT NULL,
    payment_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER,
    approval_status TEXT NOT NULL DEFAULT 'approved' CHECK(approval_status IN ('pending', 'approved', 'rejected')),
    approved_by TEXT NOT NULL DEFAULT '',
    approved_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES accounting_contacts(id),
    FOREIGN KEY (expense_account_id) REFERENCES accounts(id),
    FOREIGN KEY (payment_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
)"""

_EXPENSES_COLUMNS = (
    "id, business_id, vendor_id, expense_date, reference, description, amount,"
    " expense_account_id, payment_account_id, journal_entry_id,"
    " approval_status, approved_by, approved_at, created_at"
)


def _m007_expense_approval(conn: sqlite3.Connection) -> None:
    """Approval columns plus a rebuild making journal_entry_id nullable."""
    add_column(
        conn, "expenses", "approval_status",
        "TEXT NOT NULL DEFAULT 'approved'"
        " CHECK(approval_status IN ('pending', 'approved', 'rejected'))",
    )
    add_column(conn, "expenses", "approved_by", "TEXT NOT NULL DEFAULT ''")
    add_column(conn, "expenses", "approved_at", "TEXT")
    if not table_exists(conn, "expenses"):
        return
    info = conn.execute("PRAGMA table_info(expenses)").fetchall()
    journal_col = next((r for r in info if r["name"] == "journal_entry_id"), None)
    if journal_col is None or not journal_col["notnull"]:
        return
    conn.execute(_EXPENSES_REBUILD)
    conn.execute(
        f"INSERT INTO expenses_new ({_EXPENSES_COLUMNS})"
        f" SELECT {_EXPENSES_COLUMNS} FROM expenses"
    )
    conn.execute("DROP TABLE expenses")
    conn.execute("ALTER TABLE expenses_new RENAME TO expenses")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_expenses_business"
        " ON expenses(business_id, expense_date)"
    )


def _m008_user_business_access(conn: sqlite3.Connection) -> None:
    """User-to-business grants; the upgrade fails closed.

    Only existing global admins become owners of existing businesses so
    administration is not lost. Every other user receives no automatic
    grants — an owner must assign their memberships explicitly after the
    upgrade.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS user_business_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    business_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK(role IN ('owner', 'editor', 'viewer')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, business_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
)"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uba_user ON user_business_access(user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_uba_business ON user_business_access(business_id)"
    )
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO user_business_access"
        " (user_id, business_id, role, created_at, updated_at)"
        " SELECT u.id, b.id, 'owner', ?, ?"
        " FROM users u CROSS JOIN businesses b WHERE u.role = 'admin'",
        (now, now),
    )


_EMPLOYEES_REBUILD = """CREATE TABLE employees_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    position TEXT,
    pay_type TEXT NOT NULL CHECK(pay_type IN ('hourly', 'salary')),
    pay_frequency TEXT NOT NULL DEFAULT 'biweekly' CHECK(pay_frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly', 'annual')),
    rate REAL NOT NULL CHECK(rate > 0),
    state TEXT NOT NULL DEFAULT '',
    filing_status TEXT NOT NULL DEFAULT 'single' CHECK(filing_status IN ('single', 'married', 'hoh')),
    federal_withholding REAL NOT NULL DEFAULT 0 CHECK(federal_withholding >= 0),
    dependents INTEGER NOT NULL DEFAULT 0 CHECK(dependents >= 0),
    other_income REAL NOT NULL DEFAULT 0 CHECK(other_income >= 0),
    w4_deductions REAL NOT NULL DEFAULT 0 CHECK(w4_deductions >= 0),
    multiple_jobs INTEGER NOT NULL DEFAULT 0 CHECK(multiple_jobs IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
)"""

_EMPLOYEES_COLUMNS = (
    "id, business_id, name, position, pay_type, pay_frequency, rate, state,"
    " filing_status, federal_withholding, dependents, other_income,"
    " w4_deductions, multiple_jobs, created_at, updated_at"
)

_PAY_PERIODS_REBUILD = """CREATE TABLE pay_periods_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    pay_date TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
)"""

_PAY_PERIODS_COLUMNS = (
    "id, business_id, start_date, end_date, pay_date, status, created_at"
)


def _m009_payroll_business_scope(conn: sqlite3.Connection) -> None:
    """Scope payroll to a business: rebuild employees and pay_periods with a
    NOT NULL business_id and attach every pre-existing payroll row to one
    business.

    Strategy for existing unscoped rows:
    - exactly one business exists -> the payroll belongs to it;
    - zero or several businesses -> a dedicated "Migrated Payroll" business
      is created and every global admin receives owner access (same
      fail-closed rule as migration 8), so legacy payroll stays reachable
      only by administrators until ownership is reassigned.

    Payslips, deductions and employee_ytd need no column: they are scoped
    through their employee/period parents, which all land in the same
    business. The rebuild runs with foreign_keys OFF (see run_migrations)
    because child tables reference the tables being replaced.
    """
    rebuild_employees = not column_exists(conn, "employees", "business_id")
    rebuild_periods = not column_exists(conn, "pay_periods", "business_id")
    if not rebuild_employees and not rebuild_periods:
        return

    has_payroll = (
        conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
        + conn.execute("SELECT COUNT(*) AS n FROM pay_periods").fetchone()["n"]
    ) > 0

    business_id: int | None = None
    if has_payroll:
        row = conn.execute("SELECT id FROM businesses ORDER BY id").fetchall()
        if len(row) == 1:
            business_id = row[0]["id"]
        else:
            admins = conn.execute(
                "SELECT id FROM users WHERE role = 'admin'"
            ).fetchall()
            if not admins:
                raise RuntimeError(
                    "Cannot migrate unscoped payroll rows: the database has"
                    " legacy payroll data but no admin user to own the"
                    " 'Migrated Payroll' business. Register a global admin"
                    " account and restart so migration 9 can finish."
                )
            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "INSERT INTO businesses"
                " (legal_name, entity_type, created_at, updated_at)"
                " VALUES ('Migrated Payroll', 'llc', ?, ?)",
                (now, now),
            )
            business_id = cursor.lastrowid
            conn.execute(
                "INSERT OR IGNORE INTO user_business_access"
                " (user_id, business_id, role, created_at, updated_at)"
                " SELECT u.id, ?, 'owner', ?, ?"
                " FROM users u WHERE u.role = 'admin'",
                (business_id, now, now),
            )

    if rebuild_employees:
        conn.execute(_EMPLOYEES_REBUILD)
        conn.execute(
            f"INSERT INTO employees_new ({_EMPLOYEES_COLUMNS})"
            f" SELECT {_EMPLOYEES_COLUMNS.replace('business_id', '? AS business_id', 1)}"
            " FROM employees",
            (business_id,),
        )
        conn.execute("DROP TABLE employees")
        conn.execute("ALTER TABLE employees_new RENAME TO employees")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_employees_business ON employees(business_id)"
    )
    if rebuild_periods:
        conn.execute(_PAY_PERIODS_REBUILD)
        conn.execute(
            f"INSERT INTO pay_periods_new ({_PAY_PERIODS_COLUMNS})"
            f" SELECT {_PAY_PERIODS_COLUMNS.replace('business_id', '? AS business_id', 1)}"
            " FROM pay_periods",
            (business_id,),
        )
        conn.execute("DROP TABLE pay_periods")
        conn.execute("ALTER TABLE pay_periods_new RENAME TO pay_periods")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pay_periods_business ON pay_periods(business_id)"
    )


def _m010_journal_entries_depreciation_asset(conn: sqlite3.Connection) -> None:
    """Link depreciation journal entries to their asset.

    Adds ``depreciation_asset_id`` to journal_entries so per-asset
    depreciation can be computed without aggregating the shared
    accumulated-depreciation account across unrelated assets. Entries
    created before this column existed are backfilled from their
    ``DEP-<asset_id>`` reference convention.
    """
    if not table_exists(conn, "journal_entries"):
        return
    add_column(conn, "journal_entries", "depreciation_asset_id", "INTEGER")
    conn.execute(
        "UPDATE journal_entries"
        " SET depreciation_asset_id = CAST(SUBSTR(reference, 5) AS INTEGER)"
        " WHERE depreciation_asset_id IS NULL"
        " AND reference GLOB 'DEP-[0-9]*'"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_entries_depreciation_asset"
        " ON journal_entries(depreciation_asset_id)"
    )


def _m011_login_attempts(conn: sqlite3.Connection) -> None:
    """Store failed-login attempts in SQLite so the rate limit is shared
    across processes/workers and expired rows are pruned instead of held
    in process memory."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    remote_addr TEXT NOT NULL,
    username TEXT NOT NULL,
    attempted_at REAL NOT NULL
)"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_attempts_key"
        " ON login_attempts(remote_addr, username, attempted_at)"
    )


MIGRATIONS: list[Migration] = [
    Migration(1, "employees_pay_frequency", _m001_employees_pay_frequency),
    Migration(2, "employee_w4_fields", _m002_employee_w4_fields),
    Migration(3, "payslip_wage_bases", _m003_payslip_wage_bases),
    Migration(4, "accounts_group_id", _m004_accounts_group_id),
    Migration(5, "journal_lines_cost_center", _m005_journal_lines_cost_center),
    Migration(6, "contacts_1099_fields", _m006_contacts_1099_fields),
    Migration(7, "expense_approval", _m007_expense_approval),
    Migration(8, "user_business_access", _m008_user_business_access),
    Migration(9, "payroll_business_scope", _m009_payroll_business_scope),
    Migration(10, "journal_entries_depreciation_asset", _m010_journal_entries_depreciation_asset),
    Migration(11, "login_attempts", _m011_login_attempts),
]

LATEST_VERSION = MIGRATIONS[-1].version
