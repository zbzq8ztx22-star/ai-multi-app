from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from flask import current_app

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "payroll.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pay_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    pay_date TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payslips (
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
    fica_wages REAL NOT NULL DEFAULT 0,
    medicare_wages REAL NOT NULL DEFAULT 0,
    other_deductions REAL NOT NULL DEFAULT 0,
    net_pay REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
    FOREIGN KEY (period_id) REFERENCES pay_periods(id) ON DELETE CASCADE,
    UNIQUE(employee_id, period_id)
);

CREATE TABLE IF NOT EXISTS payslip_deductions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payslip_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount >= 0),
    category TEXT NOT NULL DEFAULT 'other' CHECK(category IN ('tax', 'benefit', 'garnishment', 'other')),
    created_at TEXT NOT NULL,
    FOREIGN KEY (payslip_id) REFERENCES payslips(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_payslips_period ON payslips(period_id);
CREATE INDEX IF NOT EXISTS idx_payslips_employee ON payslips(employee_id);

CREATE TABLE IF NOT EXISTS employee_ytd (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    year INTEGER NOT NULL,
    gross_wages REAL NOT NULL DEFAULT 0 CHECK(gross_wages >= 0),
    fica_wages REAL NOT NULL DEFAULT 0 CHECK(fica_wages >= 0),
    medicare_wages REAL NOT NULL DEFAULT 0 CHECK(medicare_wages >= 0),
    federal_tax REAL NOT NULL DEFAULT 0 CHECK(federal_tax >= 0),
    state_tax REAL NOT NULL DEFAULT 0 CHECK(state_tax >= 0),
    fica_tax REAL NOT NULL DEFAULT 0 CHECK(fica_tax >= 0),
    medicare_tax REAL NOT NULL DEFAULT 0 CHECK(medicare_tax >= 0),
    other_deductions REAL NOT NULL DEFAULT 0 CHECK(other_deductions >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(employee_id, year),
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_employee_ytd_year ON employee_ytd(employee_id, year);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK(role IN ('admin', 'viewer')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
"""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> Path:
    try:
        configured = current_app.config.get("PAYROLL_DATABASE")
    except RuntimeError:
        configured = None
    return Path(configured) if configured else DEFAULT_DB_PATH


def get_connection() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns that were introduced after the initial schema."""
    migrations: list[tuple[str, str, str]] = [
        ("employees", "dependents", "INTEGER NOT NULL DEFAULT 0"),
        ("employees", "other_income", "REAL NOT NULL DEFAULT 0"),
        ("employees", "w4_deductions", "REAL NOT NULL DEFAULT 0"),
        ("employees", "multiple_jobs", "INTEGER NOT NULL DEFAULT 0"),
        ("payslips", "fica_wages", "REAL NOT NULL DEFAULT 0"),
        ("payslips", "medicare_wages", "REAL NOT NULL DEFAULT 0"),
    ]
    for table, column, ddl in migrations:
        if not _column_exists(conn, table, column):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)
