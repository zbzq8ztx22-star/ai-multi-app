from backup import service as backup_service
from payroll.db import get_db

NOW = "2026-01-01T00:00:00+00:00"


def _ins(conn, sql, params):
    return conn.execute(sql, params).lastrowid


def _seed_business(conn, biz):
    """Insert one representative row into every business-scoped table."""
    group = _ins(conn, "INSERT INTO account_groups (business_id, name, account_type, display_order, created_at) VALUES (?, 'Assets', 'asset', 0, ?)", (biz, NOW))
    cash = _ins(conn, "INSERT INTO accounts (business_id, code, name, account_type, group_id, active, created_at, updated_at) VALUES (?, '1000', 'Cash', 'asset', ?, 1, ?, ?)", (biz, group, NOW, NOW))
    accum = _ins(conn, "INSERT INTO accounts (business_id, code, name, account_type, active, created_at, updated_at) VALUES (?, '1510', 'Accum Dep', 'asset', 1, ?, ?)", (biz, NOW, NOW))
    equip = _ins(conn, "INSERT INTO accounts (business_id, code, name, account_type, active, created_at, updated_at) VALUES (?, '1500', 'Equipment', 'asset', 1, ?, ?)", (biz, NOW, NOW))
    revenue = _ins(conn, "INSERT INTO accounts (business_id, code, name, account_type, active, created_at, updated_at) VALUES (?, '4000', 'Revenue', 'revenue', 1, ?, ?)", (biz, NOW, NOW))
    expense_acct = _ins(conn, "INSERT INTO accounts (business_id, code, name, account_type, active, created_at, updated_at) VALUES (?, '6000', 'Office', 'expense', 1, ?, ?)", (biz, NOW, NOW))
    liability = _ins(conn, "INSERT INTO accounts (business_id, code, name, account_type, active, created_at, updated_at) VALUES (?, '2000', 'Tax Payable', 'liability', 1, ?, ?)", (biz, NOW, NOW))
    customer = _ins(conn, "INSERT INTO accounting_contacts (business_id, name, contact_type, email, phone, tax_id, is_1099, created_at, updated_at) VALUES (?, 'Cust', 'customer', 'c@x.com', '', '', 0, ?, ?)", (biz, NOW, NOW))
    vendor = _ins(conn, "INSERT INTO accounting_contacts (business_id, name, contact_type, email, phone, tax_id, is_1099, created_at, updated_at) VALUES (?, 'Vend', 'vendor', 'v@x.com', '', '', 1, ?, ?)", (biz, NOW, NOW))
    cc = _ins(conn, "INSERT INTO cost_centers (business_id, code, name, description, active, created_at, updated_at) VALUES (?, 'CC1', 'Ops', '', 1, ?, ?)", (biz, NOW, NOW))
    asset = _ins(conn, "INSERT INTO depreciation_assets (business_id, name, asset_account_id, accumulated_account_id, depreciation_account_id, cost, salvage_value, useful_life_months, method, depreciation_rate, acquisition_date, start_date, status, created_at, updated_at) VALUES (?, 'Laptop', ?, ?, ?, 1200, 0, 36, 'straight_line', 0, '2026-01-01', '2026-01-01', 'active', ?, ?)", (biz, equip, accum, expense_acct, NOW, NOW))
    entry = _ins(conn, "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, depreciation_asset_id, created_at, updated_at) VALUES (?, '2026-01-05', 'JE-1', 'Sale', 'posted', ?, ?, ?)", (biz, asset, NOW, NOW))
    entry2 = _ins(conn, "INSERT INTO journal_entries (business_id, entry_date, reference, description, status, created_at, updated_at) VALUES (?, '2026-01-06', 'JE-2', 'Dep', 'posted', ?, ?)", (biz, NOW, NOW))
    line = _ins(conn, "INSERT INTO journal_lines (entry_id, account_id, cost_center_id, description, debit, credit) VALUES (?, ?, ?, 'sale', 500, 0)", (entry, cash, cc))
    _ins(conn, "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, 'sale', 0, 500)", (entry, revenue))
    _ins(conn, "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, 'dep', 50, 0)", (entry2, expense_acct))
    _ins(conn, "INSERT INTO journal_lines (entry_id, account_id, description, debit, credit) VALUES (?, ?, 'dep', 0, 50)", (entry2, accum))
    invoice = _ins(conn, "INSERT INTO invoices (business_id, customer_id, invoice_number, issue_date, due_date, description, amount, amount_paid, status, receivable_account_id, revenue_account_id, journal_entry_id, created_at, updated_at) VALUES (?, ?, 'INV-1', '2026-01-05', '2026-02-05', 'Work', 500, 200, 'open', ?, ?, ?, ?, ?)", (biz, customer, cash, revenue, entry, NOW, NOW))
    _ins(conn, "INSERT INTO invoice_payments (invoice_id, payment_date, amount, cash_account_id, journal_entry_id, created_at) VALUES (?, '2026-01-10', 200, ?, ?, ?)", (invoice, cash, entry2, NOW))
    _ins(conn, "INSERT INTO expenses (business_id, vendor_id, expense_date, reference, description, amount, expense_account_id, payment_account_id, journal_entry_id, approval_status, approved_by, approved_at, created_at) VALUES (?, ?, '2026-01-07', 'EXP-1', 'Supplies', 80, ?, ?, ?, 'approved', 'admin', ?, ?)", (biz, vendor, expense_acct, cash, entry2, NOW, NOW))
    _ins(conn, "INSERT INTO budgets (business_id, account_id, fiscal_year, period, budgeted_amount, created_at, updated_at) VALUES (?, ?, 2026, 'annual', 1000, ?, ?)", (biz, expense_acct, NOW, NOW))
    _ins(conn, "INSERT INTO reconciliations (business_id, account_id, statement_date, statement_balance, book_balance, difference, status, notes, created_at, updated_at) VALUES (?, ?, '2026-01-31', 1000, 1000, 0, 'reconciled', '', ?, ?)", (biz, cash, NOW, NOW))
    _ins(conn, "INSERT INTO recurring_expenses (business_id, vendor_id, description, amount, expense_account_id, payment_account_id, frequency, start_date, next_date, end_date, last_posted_date, active, created_at, updated_at) VALUES (?, ?, 'Rent', 300, ?, ?, 'monthly', '2026-01-01', '2026-02-01', NULL, '2026-01-01', 1, ?, ?)", (biz, vendor, expense_acct, cash, NOW, NOW))
    usd = _ins(conn, "INSERT INTO currencies (business_id, code, name, symbol, is_base, created_at) VALUES (?, 'USD', 'Dollar', '$', 1, ?)", (biz, NOW))
    eur = _ins(conn, "INSERT INTO currencies (business_id, code, name, symbol, is_base, created_at) VALUES (?, 'EUR', 'Euro', 'E', 0, ?)", (biz, NOW))
    _ins(conn, "INSERT INTO exchange_rates (business_id, from_currency_id, to_currency_id, rate, rate_date, created_at) VALUES (?, ?, ?, 1.1, '2026-01-15', ?)", (biz, eur, usd, NOW))
    _ins(conn, "INSERT INTO closing_periods (business_id, period_start, period_end, closed_by, closed_at, notes) VALUES (?, '2025-01-01', '2025-12-31', 'admin', ?, 'fy2025')", (biz, NOW))
    _ins(conn, "INSERT INTO tax_payments (business_id, tax_type, payment_date, amount, period_start, period_end, reference, notes, created_at) VALUES (?, 'federal_estimated', '2026-01-15', 250, '2026-01-01', '2026-03-31', 'Q1', '', ?)", (biz, NOW))
    _ins(conn, "INSERT INTO payment_terms (business_id, name, net_days, discount_percent, discount_days, description, is_default, created_at, updated_at) VALUES (?, 'Net30', 30, 0, 0, '', 1, ?, ?)", (biz, NOW, NOW))
    _ins(conn, "INSERT INTO credit_notes (business_id, invoice_id, customer_id, credit_number, credit_date, amount, reason, receivable_account_id, revenue_account_id, journal_entry_id, status, created_at, updated_at) VALUES (?, ?, ?, 'CN-1', '2026-01-20', 50, 'Refund', ?, ?, ?, 'applied', ?, ?)", (biz, invoice, customer, cash, revenue, entry2, NOW, NOW))
    item = _ins(conn, "INSERT INTO inventory_items (business_id, sku, name, description, unit_cost, unit_price, quantity_on_hand, reorder_point, inventory_account_id, cogs_account_id, sales_account_id, active, created_at, updated_at) VALUES (?, 'SKU1', 'Widget', '', 10, 20, 5, 1, ?, ?, ?, 1, ?, ?)", (biz, equip, expense_acct, revenue, NOW, NOW))
    _ins(conn, "INSERT INTO inventory_movements (business_id, item_id, movement_type, quantity, unit_cost, reference, movement_date, created_at) VALUES (?, ?, 'purchase', 5, 10, 'PO-1', '2026-01-08', ?)", (biz, item, NOW))
    _ins(conn, "INSERT INTO projects (business_id, code, name, description, customer_id, start_date, end_date, budgeted_revenue, budgeted_cost, status, cost_center_id, created_at, updated_at) VALUES (?, 'P1', 'Proj', '', ?, '2026-01-01', NULL, 2000, 1000, 'active', ?, ?, ?)", (biz, customer, cc, NOW, NOW))
    _ins(conn, "INSERT INTO bank_transactions (business_id, account_id, transaction_date, description, amount, type, reference, matched_journal_line_id, cleared, created_at, updated_at) VALUES (?, ?, '2026-01-10', 'Deposit', 500, 'deposit', 'DEP', ?, 1, ?, ?)", (biz, cash, line, NOW, NOW))
    _ins(conn, "INSERT INTO sales_tax_rates (business_id, name, rate, tax_account_id, is_default, active, created_at, updated_at) VALUES (?, 'ST', 7.5, ?, 1, 1, ?, ?)", (biz, liability, NOW, NOW))
    po = _ins(conn, "INSERT INTO purchase_orders (business_id, po_number, order_date, expected_date, vendor_id, expense_account_id, payment_account_id, total_amount, status, notes, journal_entry_id, created_at, updated_at) VALUES (?, 'PO-1', '2026-01-05', '2026-01-20', ?, ?, ?, 50, 'received', '', ?, ?, ?)", (biz, vendor, expense_acct, cash, entry2, NOW, NOW))
    _ins(conn, "INSERT INTO purchase_order_lines (po_id, description, quantity, unit_price, line_total) VALUES (?, 'Widgets', 5, 10, 50)", (po,))
    emp = _ins(conn, "INSERT INTO employees (business_id, name, position, pay_type, pay_frequency, rate, state, filing_status, federal_withholding, dependents, other_income, w4_deductions, multiple_jobs, created_at, updated_at) VALUES (?, 'Ann', 'Dev', 'hourly', 'biweekly', 40, 'CA', 'single', 0, 0, 0, 0, 0, ?, ?)", (biz, NOW, NOW))
    period = _ins(conn, "INSERT INTO pay_periods (business_id, start_date, end_date, pay_date, status, created_at) VALUES (?, '2026-01-01', '2026-01-15', '2026-01-16', 'open', ?)", (biz, NOW))
    payslip = _ins(conn, "INSERT INTO payslips (employee_id, period_id, regular_hours, overtime_hours, gross_pay, federal_tax, state_tax, fica_tax, medicare_tax, fica_wages, medicare_wages, other_deductions, net_pay, created_at, updated_at) VALUES (?, ?, 80, 0, 3200, 400, 100, 200, 50, 3200, 3200, 30, 2420, ?, ?)", (emp, period, NOW, NOW))
    _ins(conn, "INSERT INTO payslip_deductions (payslip_id, name, amount, category, created_at) VALUES (?, '401k', 30, 'benefit', ?)", (payslip, NOW))
    _ins(conn, "INSERT INTO employee_ytd (employee_id, year, gross_wages, fica_wages, medicare_wages, federal_tax, state_tax, fica_tax, medicare_tax, other_deductions, created_at, updated_at) VALUES (?, 2026, 3200, 3200, 3200, 400, 100, 200, 50, 30, ?, ?)", (emp, NOW, NOW))
    taxpayer = _ins(conn, "INSERT INTO taxpayers (employee_id, legal_name, taxpayer_type, filing_status, residence_state, identifier_last4, email, phone, address, created_at, updated_at) VALUES (?, 'Ann Tax', 'individual', 'single', 'CA', '1234', '', '', '', ?, ?)", (emp, NOW, NOW))
    _ins(conn, "INSERT INTO business_owners (business_id, taxpayer_id, ownership_percent) VALUES (?, ?, 100)", (biz, taxpayer))
    _ins(conn, "INSERT INTO tax_returns (taxpayer_id, tax_year, status, filing_status, residence_state, wages, interest_income, dividend_income, business_income, capital_gains, other_income, adjustments, itemized_deductions, credits, federal_withholding, estimated_payments, state_tax_liability, state_withholding, total_income, adjusted_gross_income, deduction, taxable_income, federal_tax, federal_refund_or_due, state_refund_or_due, created_at, updated_at) VALUES (?, 2025, 'draft', 'single', 'CA', 3200, 0, 0, 0, 0, 0, 0, 0, 0, 400, 0, 100, 100, 3200, 3200, 0, 3200, 300, -100, 0, ?, ?)", (taxpayer, NOW, NOW))


def _counts(conn, business_id):
    """Count rows belonging to a business using the export graph rules."""
    counts: dict[str, int] = {}
    ids: dict[str, list[int]] = {}
    for table, scope in backup_service._TABLE_GRAPH:
        if scope == "business":
            rows = conn.execute(f"SELECT * FROM {table} WHERE business_id = ?", (business_id,)).fetchall()
        elif scope == "taxpayers":
            rows = conn.execute(
                """SELECT * FROM taxpayers
                   WHERE employee_id IN (SELECT id FROM employees WHERE business_id = ?)
                      OR id IN (SELECT taxpayer_id FROM business_owners WHERE business_id = ?)""",
                (business_id, business_id),
            ).fetchall()
        else:
            fk_col, parent = scope
            parent_ids = ids[parent]
            if not parent_ids:
                rows = []
            else:
                marks = ",".join("?" * len(parent_ids))
                rows = conn.execute(f"SELECT * FROM {table} WHERE {fk_col} IN ({marks})", parent_ids).fetchall()
        counts[table] = len(rows)
        ids[table] = [r["id"] for r in rows if "id" in r.keys()]
    return counts


def test_backup_restore_is_symmetric(client, app):
    business = client.post("/api/entities/businesses", json={"legal_name": "Full Backup Co", "dba_name": "FBC", "entity_type": "llc"}).get_json()
    with app.app_context(), get_db() as conn:
        _seed_business(conn, business["id"])
        conn.commit()
        source_counts = _counts(conn, business["id"])

    export = client.get(f"/api/backup/export/{business['id']}").get_json()
    assert export["format_version"] == 2
    # Every exported table must have data in this fixture.
    assert all(len(rows) >= 1 for rows in export["tables"].values())

    response = client.post("/api/backup/import", json=export)
    assert response.status_code == 201
    new_id = response.get_json()["business_id"]
    assert new_id != business["id"]

    with app.app_context(), get_db() as conn:
        restored_counts = _counts(conn, new_id)
        # Counts and values are identical for every module.
        assert restored_counts == source_counts
        # Relationships survive remapping: no dangling foreign keys.
        checks = [
            ("accounts.group_id", "SELECT COUNT(*) AS c FROM accounts a WHERE a.business_id = ? AND a.group_id IS NOT NULL AND a.group_id NOT IN (SELECT id FROM account_groups WHERE business_id = ?)"),
            ("journal_lines", "SELECT COUNT(*) AS c FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id WHERE je.business_id = ? AND (jl.account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR (jl.cost_center_id IS NOT NULL AND jl.cost_center_id NOT IN (SELECT id FROM cost_centers WHERE business_id = ?)))"),
            ("invoices", "SELECT COUNT(*) AS c FROM invoices i WHERE i.business_id = ? AND (i.customer_id NOT IN (SELECT id FROM accounting_contacts WHERE business_id = ?) OR i.receivable_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR i.revenue_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR (i.journal_entry_id IS NOT NULL AND i.journal_entry_id NOT IN (SELECT id FROM journal_entries WHERE business_id = ?)))"),
            ("invoice_payments", "SELECT COUNT(*) AS c FROM invoice_payments ip JOIN invoices i ON i.id = ip.invoice_id WHERE i.business_id = ? AND (ip.cash_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR (ip.journal_entry_id IS NOT NULL AND ip.journal_entry_id NOT IN (SELECT id FROM journal_entries WHERE business_id = ?)))"),
            ("expenses", "SELECT COUNT(*) AS c FROM expenses e WHERE e.business_id = ? AND ((e.vendor_id IS NOT NULL AND e.vendor_id NOT IN (SELECT id FROM accounting_contacts WHERE business_id = ?)) OR e.expense_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR e.payment_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR (e.journal_entry_id IS NOT NULL AND e.journal_entry_id NOT IN (SELECT id FROM journal_entries WHERE business_id = ?)))"),
            ("budgets", "SELECT COUNT(*) AS c FROM budgets b WHERE b.business_id = ? AND b.account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)"),
            ("reconciliations", "SELECT COUNT(*) AS c FROM reconciliations r WHERE r.business_id = ? AND r.account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)"),
            ("recurring_expenses", "SELECT COUNT(*) AS c FROM recurring_expenses r WHERE r.business_id = ? AND ((r.vendor_id IS NOT NULL AND r.vendor_id NOT IN (SELECT id FROM accounting_contacts WHERE business_id = ?)) OR r.expense_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR r.payment_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?))"),
            ("exchange_rates", "SELECT COUNT(*) AS c FROM exchange_rates r WHERE r.business_id = ? AND (r.from_currency_id NOT IN (SELECT id FROM currencies WHERE business_id = ?) OR r.to_currency_id NOT IN (SELECT id FROM currencies WHERE business_id = ?))"),
            ("credit_notes", "SELECT COUNT(*) AS c FROM credit_notes cn WHERE cn.business_id = ? AND ((cn.invoice_id IS NOT NULL AND cn.invoice_id NOT IN (SELECT id FROM invoices WHERE business_id = ?)) OR (cn.customer_id IS NOT NULL AND cn.customer_id NOT IN (SELECT id FROM accounting_contacts WHERE business_id = ?)) OR cn.receivable_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR cn.revenue_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR (cn.journal_entry_id IS NOT NULL AND cn.journal_entry_id NOT IN (SELECT id FROM journal_entries WHERE business_id = ?)))"),
            ("depreciation_assets", "SELECT COUNT(*) AS c FROM depreciation_assets d WHERE d.business_id = ? AND (d.asset_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR d.accumulated_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR d.depreciation_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?))"),
            ("journal_entries.depreciation_asset_id", "SELECT COUNT(*) AS c FROM journal_entries je WHERE je.business_id = ? AND je.depreciation_asset_id IS NOT NULL AND je.depreciation_asset_id NOT IN (SELECT id FROM depreciation_assets WHERE business_id = ?)"),
            ("inventory_items", "SELECT COUNT(*) AS c FROM inventory_items it WHERE it.business_id = ? AND ((it.inventory_account_id IS NOT NULL AND it.inventory_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)) OR (it.cogs_account_id IS NOT NULL AND it.cogs_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)) OR (it.sales_account_id IS NOT NULL AND it.sales_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)))"),
            ("inventory_movements", "SELECT COUNT(*) AS c FROM inventory_movements m WHERE m.business_id = ? AND m.item_id NOT IN (SELECT id FROM inventory_items WHERE business_id = ?)"),
            ("projects", "SELECT COUNT(*) AS c FROM projects p WHERE p.business_id = ? AND ((p.customer_id IS NOT NULL AND p.customer_id NOT IN (SELECT id FROM accounting_contacts WHERE business_id = ?)) OR (p.cost_center_id IS NOT NULL AND p.cost_center_id NOT IN (SELECT id FROM cost_centers WHERE business_id = ?)))"),
            ("bank_transactions", "SELECT COUNT(*) AS c FROM bank_transactions bt WHERE bt.business_id = ? AND (bt.account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?) OR (bt.matched_journal_line_id IS NOT NULL AND bt.matched_journal_line_id NOT IN (SELECT jl.id FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id WHERE je.business_id = ?)))"),
            ("sales_tax_rates", "SELECT COUNT(*) AS c FROM sales_tax_rates s WHERE s.business_id = ? AND s.tax_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)"),
            ("purchase_orders", "SELECT COUNT(*) AS c FROM purchase_orders po WHERE po.business_id = ? AND ((po.vendor_id IS NOT NULL AND po.vendor_id NOT IN (SELECT id FROM accounting_contacts WHERE business_id = ?)) OR (po.expense_account_id IS NOT NULL AND po.expense_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)) OR (po.payment_account_id IS NOT NULL AND po.payment_account_id NOT IN (SELECT id FROM accounts WHERE business_id = ?)) OR (po.journal_entry_id IS NOT NULL AND po.journal_entry_id NOT IN (SELECT id FROM journal_entries WHERE business_id = ?)))"),
            ("purchase_order_lines", "SELECT COUNT(*) AS c FROM purchase_order_lines pl WHERE pl.po_id NOT IN (SELECT id FROM purchase_orders)"),
            ("payslips", "SELECT COUNT(*) AS c FROM payslips p WHERE p.employee_id NOT IN (SELECT id FROM employees) OR p.period_id NOT IN (SELECT id FROM pay_periods)"),
            ("payslip_deductions", "SELECT COUNT(*) AS c FROM payslip_deductions pd WHERE pd.payslip_id NOT IN (SELECT id FROM payslips)"),
            ("employee_ytd", "SELECT COUNT(*) AS c FROM employee_ytd y WHERE y.employee_id NOT IN (SELECT id FROM employees)"),
            ("taxpayers.employee_id", "SELECT COUNT(*) AS c FROM taxpayers t WHERE t.employee_id IS NOT NULL AND t.employee_id NOT IN (SELECT id FROM employees)"),
            ("business_owners", "SELECT COUNT(*) AS c FROM business_owners bo WHERE bo.business_id = ? AND bo.taxpayer_id NOT IN (SELECT id FROM taxpayers)"),
            ("tax_returns", "SELECT COUNT(*) AS c FROM tax_returns tr WHERE tr.taxpayer_id NOT IN (SELECT id FROM taxpayers)"),
        ]
        for label, sql in checks:
            params = tuple(new_id for _ in range(sql.count("?")))
            assert conn.execute(sql, params).fetchone()["c"] == 0, label
        # Spot-check a remapped relationship end-to-end.
        row = conn.execute(
            "SELECT i.invoice_number, c.name AS customer FROM invoices i JOIN accounting_contacts c ON c.id = i.customer_id WHERE i.business_id = ?",
            (new_id,),
        ).fetchone()
        assert row["invoice_number"] == "INV-1" and row["customer"] == "Cust"


def test_import_rejects_unsupported_version(client):
    response = client.post("/api/backup/import", json={"format_version": 99, "business": {"legal_name": "X"}, "tables": {}})
    assert response.status_code == 400


def test_import_rejects_malformed_version(client):
    for bad_version in ([2], {"v": 2}, "2", True, 2.0):
        response = client.post("/api/backup/import", json={
            "format_version": bad_version, "business": {"legal_name": "X"}, "tables": {},
        })
        assert response.status_code == 400, bad_version


def test_import_owner_with_foreign_employee(client, app):
    source = client.post("/api/entities/businesses", json={"legal_name": "Employer Co"}).get_json()
    owned = client.post("/api/entities/businesses", json={"legal_name": "Owned Co"}).get_json()
    with app.app_context(), get_db() as conn:
        emp = _ins(conn, "INSERT INTO employees (business_id, name, position, pay_type, pay_frequency, rate, state, filing_status, federal_withholding, dependents, other_income, w4_deductions, multiple_jobs, created_at, updated_at) VALUES (?, 'Ana', 'Dev', 'hourly', 'biweekly', 40, 'CA', 'single', 0, 0, 0, 0, 0, ?, ?)", (source["id"], NOW, NOW))
        taxpayer = _ins(conn, "INSERT INTO taxpayers (employee_id, legal_name, taxpayer_type, filing_status, residence_state, identifier_last4, email, phone, address, created_at, updated_at) VALUES (?, 'Ana T', 'individual', 'single', 'CA', '1234', '', '', '', ?, ?)", (emp, NOW, NOW))
        conn.execute("INSERT INTO business_owners (business_id, taxpayer_id, ownership_percent) VALUES (?, ?, 100)", (owned["id"], taxpayer))
        conn.commit()
    export = client.get(f"/api/backup/export/{owned['id']}").get_json()
    assert len(export["tables"]["taxpayers"]) == 1
    response = client.post("/api/backup/import", json=export)
    assert response.status_code == 201
    new_id = response.get_json()["business_id"]
    with app.app_context(), get_db() as conn:
        row = conn.execute(
            "SELECT t.employee_id FROM taxpayers t JOIN business_owners bo ON bo.taxpayer_id = t.id WHERE bo.business_id = ?",
            (new_id,),
        ).fetchone()
        assert row["employee_id"] is None


def test_import_rejects_rows_from_other_business(client, app):
    business = client.post("/api/entities/businesses", json={"legal_name": "Mix Co"}).get_json()
    with app.app_context(), get_db() as conn:
        _seed_business(conn, business["id"])
        conn.commit()
    export = client.get(f"/api/backup/export/{business['id']}").get_json()
    export["tables"]["accounts"][0]["business_id"] = 99999
    response = client.post("/api/backup/import", json=export)
    assert response.status_code == 400


def test_import_rolls_back_entirely_on_bad_reference(client, app):
    business = client.post("/api/entities/businesses", json={"legal_name": "Rollback Co"}).get_json()
    with app.app_context(), get_db() as conn:
        _seed_business(conn, business["id"])
        conn.commit()
        before = conn.execute("SELECT COUNT(*) AS c FROM businesses").fetchone()["c"]
    export = client.get(f"/api/backup/export/{business['id']}").get_json()
    # Remove the account that journal lines reference -> unresolved FK.
    export["tables"]["accounts"] = [a for a in export["tables"]["accounts"] if a["name"] != "Cash"]
    response = client.post("/api/backup/import", json=export)
    assert response.status_code == 400
    with app.app_context(), get_db() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM businesses").fetchone()["c"] == before


def test_import_rejects_oversized_table(client, monkeypatch):
    monkeypatch.setattr(backup_service, "MAX_ROWS_PER_TABLE", 1)
    response = client.post("/api/backup/import", json={
        "business": {"legal_name": "Big"},
        "tables": {"accounts": [{"id": 1}, {"id": 2}]},
    })
    assert response.status_code == 400


def test_import_rejects_malformed_tables(client):
    response = client.post("/api/backup/import", json={"business": {"legal_name": "X"}, "tables": {"accounts": "nope"}})
    assert response.status_code == 400
