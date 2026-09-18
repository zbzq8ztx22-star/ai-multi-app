"""Upgrade tests for the versioned SQLite migration system.

Build databases with historical schema definitions, run init_db() (the same
entry point used at app startup) and verify data survives, every current
table/column exists, and the process is safe to repeat.
"""
import re
import sqlite3
from pathlib import Path

from flask import Flask

from payroll.db import SCHEMA, init_db
from payroll.migrations import MIGRATIONS, MIGRATIONS_TABLE

# Payroll schema as it existed before migrations were introduced: employees
# still had salary_frequency, no W-4 columns, no employee_ytd, no users.
OLD_PAYROLL_SCHEMA = """
CREATE TABLE employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    position TEXT,
    pay_type TEXT NOT NULL CHECK(pay_type IN ('hourly', 'salary')),
    salary_frequency TEXT NOT NULL DEFAULT 'biweekly' CHECK(salary_frequency IN ('weekly', 'biweekly', 'semimonthly', 'monthly', 'annual')),
    rate REAL NOT NULL CHECK(rate > 0),
    state TEXT NOT NULL DEFAULT '',
    filing_status TEXT NOT NULL DEFAULT 'single' CHECK(filing_status IN ('single', 'married', 'hoh')),
    federal_withholding REAL NOT NULL DEFAULT 0 CHECK(federal_withholding >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE pay_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    pay_date TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
    created_at TEXT NOT NULL
);
CREATE TABLE payslips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    period_id INTEGER NOT NULL,
    regular_hours REAL NOT NULL DEFAULT 0 CHECK(regular_hours >= 0),
    overtime_hours REAL NOT NULL DEFAULT 0 CHECK(overtime_hours >= 0),
    gross_pay REAL NOT NULL DEFAULT 0,
    federal_tax REAL NOT NULL DEFAULT 0,
    state_tax REAL NOT NULL DEFAULT 0,
    fica_tax REAL NOT NULL DEFAULT 0,
    medicare_tax REAL NOT NULL DEFAULT 0,
    other_deductions REAL NOT NULL DEFAULT 0,
    net_pay REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (period_id) REFERENCES pay_periods(id) ON DELETE CASCADE,
    UNIQUE(employee_id, period_id)
);
CREATE TABLE payslip_deductions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payslip_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount >= 0),
    category TEXT NOT NULL DEFAULT 'other' CHECK(category IN ('tax', 'benefit', 'garnishment', 'other')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (payslip_id) REFERENCES payslips(id) ON DELETE CASCADE
);
"""

# Accounting schema before vendor 1099 fields and the expense approval
# workflow: accounting_contacts lacks tax_id/is_1099, accounts lacks
# group_id, journal_lines lacks cost_center_id, expenses requires
# journal_entry_id NOT NULL and has no approval columns.
OLD_ACCOUNTING_SCHEMA = """
CREATE TABLE businesses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    legal_name TEXT NOT NULL,
    dba_name TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL CHECK(entity_type IN ('sole_proprietorship', 'llc', 'partnership', 's_corp', 'c_corp', 'nonprofit')),
    ein_last4 TEXT NOT NULL DEFAULT '',
    formation_state TEXT NOT NULL DEFAULT '',
    fiscal_year_end TEXT NOT NULL DEFAULT '12-31',
    accounting_method TEXT NOT NULL DEFAULT 'cash' CHECK(accounting_method IN ('cash', 'accrual')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE accounting_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    contact_type TEXT NOT NULL CHECK(contact_type IN ('customer', 'vendor', 'both')),
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, code),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'posted' CHECK(status IN ('draft', 'posted')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);
CREATE TABLE journal_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    debit REAL NOT NULL DEFAULT 0 CHECK(debit >= 0),
    credit REAL NOT NULL DEFAULT 0 CHECK(credit >= 0),
    CHECK((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)),
    FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT
);
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    vendor_id INTEGER,
    expense_date TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    expense_account_id INTEGER NOT NULL,
    payment_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES accounting_contacts(id),
    FOREIGN KEY (expense_account_id) REFERENCES accounts(id),
    FOREIGN KEY (payment_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
);
"""


def _run_init(db_path: Path) -> None:
    app = Flask("migration-test")
    app.config["PAYROLL_DATABASE"] = str(db_path)
    with app.app_context():
        init_db()


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    return {row["name"]: row for row in conn.execute(f"PRAGMA table_info({table})")}


def _expected_schema() -> dict[str, list[str]]:
    expected: dict[str, list[str]] = {}
    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", SCHEMA, re.S
    ):
        name, body = match.groups()
        columns = []
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith(("FOREIGN", "UNIQUE", "CHECK", "PRIMARY")):
                continue
            columns.append(line.split()[0].rstrip(","))
        expected[name] = columns
    return expected


def _all_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
        " AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {row["name"] for row in rows}


def _seed_old_payroll(db_path: Path) -> None:
    conn = _connect(db_path)
    conn.executescript(OLD_PAYROLL_SCHEMA)
    conn.execute(
        "INSERT INTO employees (name, position, pay_type, salary_frequency, rate,"
        " created_at, updated_at) VALUES ('Ada', 'Engineer', 'salary', 'monthly',"
        " 9000, '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO pay_periods (start_date, end_date, created_at)"
        " VALUES ('2026-01-01', '2026-01-15', '2026-01-15')"
    )
    conn.execute(
        "INSERT INTO payslips (employee_id, period_id, regular_hours, gross_pay,"
        " net_pay, created_at, updated_at) VALUES (1, 1, 80, 4500, 3800,"
        " '2026-01-15', '2026-01-15')"
    )
    conn.commit()
    conn.close()


def _seed_old_accounting(db_path: Path) -> None:
    conn = _connect(db_path)
    conn.executescript(OLD_ACCOUNTING_SCHEMA)
    conn.execute(
        "INSERT INTO businesses (legal_name, entity_type, created_at, updated_at)"
        " VALUES ('Acme LLC', 'llc', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO accounting_contacts (business_id, name, contact_type,"
        " created_at, updated_at) VALUES (1, 'Vendor Co', 'vendor', '2026-01-01',"
        " '2026-01-01')"
    )
    for code in ("1000", "5000"):
        conn.execute(
            "INSERT INTO accounts (business_id, code, name, account_type,"
            " created_at, updated_at) VALUES (1, ?, 'Acct', 'expense',"
            " '2026-01-01', '2026-01-01')",
            (code,),
        )
    conn.execute(
        "INSERT INTO journal_entries (business_id, entry_date, description,"
        " created_at, updated_at) VALUES (1, '2026-01-02', 'Entry',"
        " '2026-01-02', '2026-01-02')"
    )
    conn.execute(
        "INSERT INTO expenses (business_id, vendor_id, expense_date, description,"
        " amount, expense_account_id, payment_account_id, journal_entry_id,"
        " created_at) VALUES (1, 1, '2026-01-03', 'Old expense', 42.5, 2, 1, 1,"
        " '2026-01-03')"
    )
    conn.commit()
    conn.close()


def test_upgrade_oldest_payroll_schema_preserves_data(tmp_path):
    db_path = tmp_path / "old.db"
    _seed_old_payroll(db_path)

    _run_init(db_path)
    conn = _connect(db_path)

    employee = conn.execute("SELECT * FROM employees").fetchone()
    assert "salary_frequency" not in employee.keys()
    assert employee["pay_frequency"] == "monthly"
    assert employee["dependents"] == 0

    payslip = conn.execute("SELECT * FROM payslips").fetchone()
    assert payslip["gross_pay"] == 4500
    assert payslip["fica_wages"] == 0

    assert conn.execute("SELECT COUNT(*) FROM pay_periods").fetchone()[0] == 1


def test_upgrade_adds_every_current_table_and_column(tmp_path):
    db_path = tmp_path / "old.db"
    _seed_old_payroll(db_path)
    _run_init(db_path)
    conn = _connect(db_path)

    tables = _all_tables(conn)
    expected = _expected_schema()
    for table, columns in expected.items():
        assert table in tables, f"missing table {table}"
        actual = _table_columns(conn, table)
        for column in columns:
            assert column in actual, f"missing column {table}.{column}"


def test_upgrade_expenses_rebuild_makes_journal_entry_nullable(tmp_path):
    db_path = tmp_path / "old.db"
    _seed_old_accounting(db_path)
    _run_init(db_path)
    conn = _connect(db_path)

    columns = _table_columns(conn, "expenses")
    assert columns["journal_entry_id"]["notnull"] == 0
    for column in ("approval_status", "approved_by", "approved_at"):
        assert column in columns

    expense = conn.execute("SELECT * FROM expenses").fetchone()
    assert expense["description"] == "Old expense"
    assert expense["amount"] == 42.5
    assert expense["journal_entry_id"] == 1
    assert expense["approval_status"] == "approved"

    conn.execute(
        "INSERT INTO expenses (business_id, expense_date, description, amount,"
        " expense_account_id, payment_account_id, journal_entry_id, created_at)"
        " VALUES (1, '2026-02-01', 'No journal yet', 10, 2, 1, NULL, '2026-02-01')"
    )


def test_upgrade_adds_1099_and_group_columns(tmp_path):
    db_path = tmp_path / "old.db"
    _seed_old_accounting(db_path)
    _run_init(db_path)
    conn = _connect(db_path)

    assert "is_1099" in _table_columns(conn, "accounting_contacts")
    assert "tax_id" in _table_columns(conn, "accounting_contacts")
    assert "group_id" in _table_columns(conn, "accounts")
    assert "cost_center_id" in _table_columns(conn, "journal_lines")

    contact = conn.execute("SELECT * FROM accounting_contacts").fetchone()
    assert contact["name"] == "Vendor Co"
    assert contact["is_1099"] == 0


def test_migrations_recorded_and_idempotent(tmp_path):
    db_path = tmp_path / "old.db"
    _seed_old_payroll(db_path)

    _run_init(db_path)
    conn = _connect(db_path)
    rows = conn.execute(
        f"SELECT version FROM {MIGRATIONS_TABLE} ORDER BY version"
    ).fetchall()
    assert [row["version"] for row in rows] == [m.version for m in MIGRATIONS]
    conn.close()

    # Second run must not fail, duplicate rows, or lose data.
    _run_init(db_path)
    conn = _connect(db_path)
    count = conn.execute(f"SELECT COUNT(*) FROM {MIGRATIONS_TABLE}").fetchone()[0]
    assert count == len(MIGRATIONS)
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 1


def test_migration_8_backfill_is_fail_closed(tmp_path):
    """Existing admins keep administrative ownership; other users get nothing."""
    db_path = tmp_path / "old.db"
    _seed_old_accounting(db_path)
    conn = _connect(db_path)
    conn.execute(
        """CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK(role IN ('admin', 'viewer')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""
    )
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at,"
        " updated_at) VALUES ('boss', 'x', 'admin', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO users (username, password_hash, role, created_at,"
        " updated_at) VALUES ('clerk', 'x', 'viewer', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    _run_init(db_path)
    conn = _connect(db_path)

    grants = conn.execute(
        "SELECT user_id, business_id, role FROM user_business_access"
        " ORDER BY user_id"
    ).fetchall()
    # The admin becomes owner of the existing business so administration
    # survives the upgrade...
    assert [
        (row["user_id"], row["business_id"], row["role"]) for row in grants
    ] == [(1, 1, "owner")]
    # ...but the non-admin user is not granted access to any business.
    assert all(row["user_id"] != 2 for row in grants)

    # Business data itself is preserved.
    assert conn.execute("SELECT COUNT(*) FROM businesses").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 2
    conn.close()

    # Re-running migrations neither duplicates nor widens the grants.
    _run_init(db_path)
    conn = _connect(db_path)
    assert (
        conn.execute("SELECT COUNT(*) FROM user_business_access").fetchone()[0]
        == 1
    )


def test_fresh_install_ends_at_latest_version(tmp_path):
    db_path = tmp_path / "fresh.db"
    _run_init(db_path)
    conn = _connect(db_path)

    rows = conn.execute(
        f"SELECT version FROM {MIGRATIONS_TABLE} ORDER BY version"
    ).fetchall()
    assert [row["version"] for row in rows] == [m.version for m in MIGRATIONS]
    assert "expenses" in _all_tables(conn)
    columns = _table_columns(conn, "expenses")
    assert columns["journal_entry_id"]["notnull"] == 0
