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

CREATE TABLE IF NOT EXISTS taxpayers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER,
    legal_name TEXT NOT NULL,
    taxpayer_type TEXT NOT NULL DEFAULT 'individual' CHECK(taxpayer_type IN ('individual', 'business')),
    filing_status TEXT NOT NULL DEFAULT 'single' CHECK(filing_status IN ('single', 'married_joint', 'married_separate', 'hoh', 'widow', 'business')),
    residence_state TEXT NOT NULL DEFAULT '',
    identifier_last4 TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS businesses (
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

CREATE TABLE IF NOT EXISTS business_owners (
    business_id INTEGER NOT NULL,
    taxpayer_id INTEGER NOT NULL,
    ownership_percent REAL NOT NULL CHECK(ownership_percent >= 0 AND ownership_percent <= 100),
    PRIMARY KEY (business_id, taxpayer_id),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (taxpayer_id) REFERENCES taxpayers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_taxpayers_employee ON taxpayers(employee_id);
CREATE INDEX IF NOT EXISTS idx_businesses_name ON businesses(legal_name);

CREATE TABLE IF NOT EXISTS tax_returns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taxpayer_id INTEGER NOT NULL,
    tax_year INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'reviewed', 'filed')),
    filing_status TEXT NOT NULL,
    residence_state TEXT NOT NULL DEFAULT '',
    wages REAL NOT NULL DEFAULT 0,
    interest_income REAL NOT NULL DEFAULT 0,
    dividend_income REAL NOT NULL DEFAULT 0,
    business_income REAL NOT NULL DEFAULT 0,
    capital_gains REAL NOT NULL DEFAULT 0,
    other_income REAL NOT NULL DEFAULT 0,
    adjustments REAL NOT NULL DEFAULT 0,
    itemized_deductions REAL NOT NULL DEFAULT 0,
    credits REAL NOT NULL DEFAULT 0,
    federal_withholding REAL NOT NULL DEFAULT 0,
    estimated_payments REAL NOT NULL DEFAULT 0,
    state_tax_liability REAL NOT NULL DEFAULT 0,
    state_withholding REAL NOT NULL DEFAULT 0,
    total_income REAL NOT NULL DEFAULT 0,
    adjusted_gross_income REAL NOT NULL DEFAULT 0,
    deduction REAL NOT NULL DEFAULT 0,
    taxable_income REAL NOT NULL DEFAULT 0,
    federal_tax REAL NOT NULL DEFAULT 0,
    federal_refund_or_due REAL NOT NULL DEFAULT 0,
    state_refund_or_due REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(taxpayer_id, tax_year),
    FOREIGN KEY (taxpayer_id) REFERENCES taxpayers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tax_returns_taxpayer_year ON tax_returns(taxpayer_id, tax_year);

CREATE TABLE IF NOT EXISTS accounts (
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

CREATE TABLE IF NOT EXISTS journal_entries (
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

CREATE TABLE IF NOT EXISTS journal_lines (
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

CREATE INDEX IF NOT EXISTS idx_accounts_business ON accounts(business_id, code);
CREATE INDEX IF NOT EXISTS idx_entries_business_date ON journal_entries(business_id, entry_date);
CREATE INDEX IF NOT EXISTS idx_lines_entry ON journal_lines(entry_id);
CREATE INDEX IF NOT EXISTS idx_lines_account ON journal_lines(account_id);

CREATE TABLE IF NOT EXISTS accounting_contacts (
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

CREATE TABLE IF NOT EXISTS invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    customer_id INTEGER NOT NULL,
    invoice_number TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    amount_paid REAL NOT NULL DEFAULT 0 CHECK(amount_paid >= 0),
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'paid', 'void')),
    receivable_account_id INTEGER NOT NULL,
    revenue_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, invoice_number),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES accounting_contacts(id),
    FOREIGN KEY (receivable_account_id) REFERENCES accounts(id),
    FOREIGN KEY (revenue_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
);

CREATE TABLE IF NOT EXISTS invoice_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL,
    payment_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    cash_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE CASCADE,
    FOREIGN KEY (cash_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
);

CREATE TABLE IF NOT EXISTS expenses (
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

CREATE INDEX IF NOT EXISTS idx_contacts_business ON accounting_contacts(business_id, name);
CREATE INDEX IF NOT EXISTS idx_invoices_business ON invoices(business_id, issue_date);
CREATE INDEX IF NOT EXISTS idx_expenses_business ON expenses(business_id, expense_date);

CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    fiscal_year INTEGER NOT NULL,
    period TEXT NOT NULL DEFAULT 'annual' CHECK(period IN ('annual', 'q1', 'q2', 'q3', 'q4', 'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')),
    budgeted_amount REAL NOT NULL DEFAULT 0 CHECK(budgeted_amount >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, account_id, fiscal_year, period),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_budgets_business_year ON budgets(business_id, fiscal_year);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    module TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id INTEGER,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_module ON audit_log(module);

CREATE TABLE IF NOT EXISTS reconciliations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    statement_date TEXT NOT NULL,
    statement_balance REAL NOT NULL,
    book_balance REAL NOT NULL,
    difference REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'reconciled', 'discrepancy')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reconciliations_business ON reconciliations(business_id, statement_date);

CREATE TABLE IF NOT EXISTS recurring_expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    vendor_id INTEGER,
    description TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    expense_account_id INTEGER NOT NULL,
    payment_account_id INTEGER NOT NULL,
    frequency TEXT NOT NULL CHECK(frequency IN ('weekly', 'monthly', 'quarterly', 'yearly')),
    start_date TEXT NOT NULL,
    next_date TEXT NOT NULL,
    end_date TEXT,
    last_posted_date TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES accounting_contacts(id) ON DELETE SET NULL,
    FOREIGN KEY (expense_account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (payment_account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_recurring_expenses_business ON recurring_expenses(business_id, active);
CREATE INDEX IF NOT EXISTS idx_recurring_expenses_next_date ON recurring_expenses(next_date, active);

CREATE TABLE IF NOT EXISTS currencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT '$',
    is_base INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    UNIQUE(business_id, code)
);

CREATE TABLE IF NOT EXISTS exchange_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    from_currency_id INTEGER NOT NULL,
    to_currency_id INTEGER NOT NULL,
    rate REAL NOT NULL CHECK(rate > 0),
    rate_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (from_currency_id) REFERENCES currencies(id) ON DELETE CASCADE,
    FOREIGN KEY (to_currency_id) REFERENCES currencies(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_currencies_business ON currencies(business_id, code);
CREATE INDEX IF NOT EXISTS idx_exchange_rates_business ON exchange_rates(business_id, rate_date);
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


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)
