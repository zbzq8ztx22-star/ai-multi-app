from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

from flask import current_app

from .migrations import MIGRATIONS, MIGRATIONS_TABLE

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

CREATE TABLE IF NOT EXISTS user_business_access (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    business_id INTEGER NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer' CHECK(role IN ('owner', 'editor', 'viewer')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, business_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_uba_user ON user_business_access(user_id);
CREATE INDEX IF NOT EXISTS idx_uba_business ON user_business_access(business_id);

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

CREATE TABLE IF NOT EXISTS account_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    UNIQUE(business_id, name)
);

CREATE INDEX IF NOT EXISTS idx_account_groups_business ON account_groups(business_id, display_order);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK(account_type IN ('asset', 'liability', 'equity', 'revenue', 'expense')),
    group_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, code),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES account_groups(id) ON DELETE SET NULL
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
    cost_center_id INTEGER,
    description TEXT NOT NULL DEFAULT '',
    debit REAL NOT NULL DEFAULT 0 CHECK(debit >= 0),
    credit REAL NOT NULL DEFAULT 0 CHECK(credit >= 0),
    CHECK((debit > 0 AND credit = 0) OR (credit > 0 AND debit = 0)),
    FOREIGN KEY (entry_id) REFERENCES journal_entries(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE RESTRICT,
    FOREIGN KEY (cost_center_id) REFERENCES cost_centers(id) ON DELETE SET NULL
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
    tax_id TEXT NOT NULL DEFAULT '',
    is_1099 INTEGER NOT NULL DEFAULT 0 CHECK(is_1099 IN (0, 1)),
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

CREATE TABLE IF NOT EXISTS closing_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    closed_by TEXT NOT NULL DEFAULT '',
    closed_at TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    UNIQUE(business_id, period_start, period_end),
    CHECK(period_end >= period_start)
);

CREATE INDEX IF NOT EXISTS idx_closing_periods_business ON closing_periods(business_id, period_end);

CREATE TABLE IF NOT EXISTS tax_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    tax_type TEXT NOT NULL CHECK(tax_type IN ('federal_estimated', 'state_estimated', 'federal_payroll', 'state_payroll', 'sales', 'other')),
    payment_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    reference TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    CHECK(period_end >= period_start)
);

CREATE INDEX IF NOT EXISTS idx_tax_payments_business ON tax_payments(business_id, payment_date);

CREATE TABLE IF NOT EXISTS cost_centers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    UNIQUE(business_id, code)
);

CREATE INDEX IF NOT EXISTS idx_cost_centers_business ON cost_centers(business_id, code);

CREATE TABLE IF NOT EXISTS payment_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    net_days INTEGER NOT NULL DEFAULT 30 CHECK(net_days >= 0),
    discount_percent REAL NOT NULL DEFAULT 0 CHECK(discount_percent >= 0 AND discount_percent <= 100),
    discount_days INTEGER NOT NULL DEFAULT 0 CHECK(discount_days >= 0),
    description TEXT NOT NULL DEFAULT '',
    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    UNIQUE(business_id, name)
);

CREATE INDEX IF NOT EXISTS idx_payment_terms_business ON payment_terms(business_id, name);

CREATE TABLE IF NOT EXISTS credit_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    invoice_id INTEGER,
    customer_id INTEGER,
    credit_number TEXT NOT NULL,
    credit_date TEXT NOT NULL,
    amount REAL NOT NULL CHECK(amount > 0),
    reason TEXT NOT NULL DEFAULT '',
    receivable_account_id INTEGER NOT NULL,
    revenue_account_id INTEGER NOT NULL,
    journal_entry_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'applied' CHECK(status IN ('applied', 'void')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, credit_number),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (invoice_id) REFERENCES invoices(id) ON DELETE SET NULL,
    FOREIGN KEY (customer_id) REFERENCES accounting_contacts(id),
    FOREIGN KEY (receivable_account_id) REFERENCES accounts(id),
    FOREIGN KEY (revenue_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
);

CREATE INDEX IF NOT EXISTS idx_credit_notes_business ON credit_notes(business_id, credit_date);

CREATE TABLE IF NOT EXISTS depreciation_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    asset_account_id INTEGER NOT NULL,
    accumulated_account_id INTEGER NOT NULL,
    depreciation_account_id INTEGER NOT NULL,
    cost REAL NOT NULL CHECK(cost > 0),
    salvage_value REAL NOT NULL DEFAULT 0 CHECK(salvage_value >= 0),
    useful_life_months INTEGER NOT NULL CHECK(useful_life_months > 0),
    method TEXT NOT NULL DEFAULT 'straight_line' CHECK(method IN ('straight_line', 'declining_balance')),
    depreciation_rate REAL NOT NULL DEFAULT 0 CHECK(depreciation_rate >= 0 AND depreciation_rate <= 100),
    acquisition_date TEXT NOT NULL,
    start_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'fully_depreciated', 'disposed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (asset_account_id) REFERENCES accounts(id),
    FOREIGN KEY (accumulated_account_id) REFERENCES accounts(id),
    FOREIGN KEY (depreciation_account_id) REFERENCES accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_depreciation_assets_business ON depreciation_assets(business_id, status);

CREATE TABLE IF NOT EXISTS inventory_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    unit_cost REAL NOT NULL DEFAULT 0 CHECK(unit_cost >= 0),
    unit_price REAL NOT NULL DEFAULT 0 CHECK(unit_price >= 0),
    quantity_on_hand REAL NOT NULL DEFAULT 0,
    reorder_point REAL NOT NULL DEFAULT 0 CHECK(reorder_point >= 0),
    inventory_account_id INTEGER,
    cogs_account_id INTEGER,
    sales_account_id INTEGER,
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (inventory_account_id) REFERENCES accounts(id),
    FOREIGN KEY (cogs_account_id) REFERENCES accounts(id),
    FOREIGN KEY (sales_account_id) REFERENCES accounts(id),
    UNIQUE(business_id, sku)
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    item_id INTEGER NOT NULL,
    movement_type TEXT NOT NULL CHECK(movement_type IN ('purchase', 'sale', 'adjustment', 'return')),
    quantity REAL NOT NULL,
    unit_cost REAL NOT NULL DEFAULT 0,
    reference TEXT NOT NULL DEFAULT '',
    movement_date TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (item_id) REFERENCES inventory_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inventory_items_business ON inventory_items(business_id, sku);
CREATE INDEX IF NOT EXISTS idx_inventory_movements_business ON inventory_movements(business_id, movement_date);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    customer_id INTEGER,
    start_date TEXT NOT NULL,
    end_date TEXT,
    budgeted_revenue REAL NOT NULL DEFAULT 0 CHECK(budgeted_revenue >= 0),
    budgeted_cost REAL NOT NULL DEFAULT 0 CHECK(budgeted_cost >= 0),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'on_hold', 'cancelled')),
    cost_center_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (customer_id) REFERENCES accounting_contacts(id),
    FOREIGN KEY (cost_center_id) REFERENCES cost_centers(id) ON DELETE SET NULL,
    UNIQUE(business_id, code)
);

CREATE INDEX IF NOT EXISTS idx_projects_business ON projects(business_id, status);

CREATE TABLE IF NOT EXISTS bank_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    account_id INTEGER NOT NULL,
    transaction_date TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    amount REAL NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('deposit', 'withdrawal', 'fee', 'interest')),
    reference TEXT NOT NULL DEFAULT '',
    matched_journal_line_id INTEGER,
    cleared INTEGER NOT NULL DEFAULT 0 CHECK(cleared IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (account_id) REFERENCES accounts(id),
    FOREIGN KEY (matched_journal_line_id) REFERENCES journal_lines(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_bank_transactions_business ON bank_transactions(business_id, transaction_date);
CREATE INDEX IF NOT EXISTS idx_bank_transactions_account ON bank_transactions(account_id, cleared);

CREATE TABLE IF NOT EXISTS sales_tax_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    rate REAL NOT NULL CHECK(rate >= 0 AND rate <= 100),
    tax_account_id INTEGER,
    is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (tax_account_id) REFERENCES accounts(id),
    UNIQUE(business_id, name)
);

CREATE INDEX IF NOT EXISTS idx_sales_tax_rates_business ON sales_tax_rates(business_id, active);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_id INTEGER NOT NULL,
    po_number TEXT NOT NULL,
    order_date TEXT NOT NULL,
    expected_date TEXT,
    vendor_id INTEGER,
    expense_account_id INTEGER NOT NULL,
    payment_account_id INTEGER NOT NULL,
    total_amount REAL NOT NULL DEFAULT 0 CHECK(total_amount >= 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'sent', 'received', 'cancelled')),
    notes TEXT NOT NULL DEFAULT '',
    journal_entry_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(business_id, po_number),
    FOREIGN KEY (business_id) REFERENCES businesses(id) ON DELETE CASCADE,
    FOREIGN KEY (vendor_id) REFERENCES accounting_contacts(id),
    FOREIGN KEY (expense_account_id) REFERENCES accounts(id),
    FOREIGN KEY (payment_account_id) REFERENCES accounts(id),
    FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id)
);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_id INTEGER NOT NULL,
    description TEXT NOT NULL,
    quantity REAL NOT NULL CHECK(quantity > 0),
    unit_price REAL NOT NULL CHECK(unit_price >= 0),
    line_total REAL NOT NULL CHECK(line_total >= 0),
    FOREIGN KEY (po_id) REFERENCES purchase_orders(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_purchase_orders_business ON purchase_orders(business_id, status);
CREATE INDEX IF NOT EXISTS idx_purchase_order_lines_po ON purchase_order_lines(po_id);
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


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {MIGRATIONS_TABLE} ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL)"
    )


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    _ensure_migrations_table(conn)
    rows = conn.execute(f"SELECT version FROM {MIGRATIONS_TABLE}").fetchall()
    return {row["version"] for row in rows}


def run_migrations(conn: sqlite3.Connection) -> list[int]:
    """Apply pending migrations, each in its own transaction.

    Returns the versions applied during this call. Never removes data; a
    failed migration rolls back and re-raises so init_db fails loudly.
    """
    applied = applied_versions(conn)
    ran: list[int] = []
    for migration in MIGRATIONS:
        if migration.version in applied:
            continue
        conn.execute("BEGIN")
        try:
            migration.apply(conn)
            conn.execute(
                f"INSERT INTO {MIGRATIONS_TABLE} (version, name, applied_at)"
                " VALUES (?, ?, ?)",
                (migration.version, migration.name, now_utc()),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        ran.append(migration.version)
    return ran


def init_db() -> None:
    """Create missing tables from SCHEMA, then apply pending migrations.

    SCHEMA uses CREATE TABLE IF NOT EXISTS, so it only fills gaps on existing
    databases at the latest definition; numbered migrations then upgrade
    pre-existing tables (renames, added columns, rebuilds). Runs at app
    startup inside init_app(), before any request is served.
    """
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _ensure_migrations_table(conn)
        run_migrations(conn)
        conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)
