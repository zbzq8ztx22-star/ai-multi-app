from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _setup(client, name="Reports LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    receivable = _account(client, business["id"], "1100", "Accounts Receivable", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Office Expense", "expense")
    liability = _account(client, business["id"], "2000", "Accounts Payable", "liability")
    equity = _account(client, business["id"], "3000", "Owner Equity", "equity")
    return business, cash, receivable, revenue, expense, liability, equity


def test_profit_and_loss_summarizes_revenue_and_expenses(client):
    business, cash, _, revenue, expense, _, _ = _setup(client)
    _entry(client, business["id"], "2026-01-10", "Sale", [{"account_id": cash["id"], "debit": 1000}, {"account_id": revenue["id"], "credit": 1000}])
    _entry(client, business["id"], "2026-01-20", "Cost", [{"account_id": expense["id"], "debit": 300}, {"account_id": cash["id"], "credit": 300}])
    pl = client.get(f"/api/accounting/reports/profit-loss?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert pl["total_revenue"] == 1000
    assert pl["total_expenses"] == 300
    assert pl["net_income"] == 700
    assert len(pl["revenue"]) == 1
    assert len(pl["expenses"]) == 1


def test_profit_and_loss_date_filtering(client):
    business, cash, _, revenue, _, _, _ = _setup(client)
    _entry(client, business["id"], "2026-01-10", "Jan sale", [{"account_id": cash["id"], "debit": 500}, {"account_id": revenue["id"], "credit": 500}])
    _entry(client, business["id"], "2026-06-10", "Jun sale", [{"account_id": cash["id"], "debit": 800}, {"account_id": revenue["id"], "credit": 800}])
    pl = client.get(f"/api/accounting/reports/profit-loss?business_id={business['id']}&start_date=2026-02-01&end_date=2026-12-31").get_json()
    assert pl["total_revenue"] == 800
    assert pl["total_expenses"] == 0
    assert pl["net_income"] == 800


def test_balance_sheet_balances_with_assets_liabilities_equity(client):
    business, cash, _, _, _, liability, equity = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 2000}, {"account_id": equity["id"], "credit": 2000}])
    _entry(client, business["id"], "2026-01-05", "Loan", [{"account_id": cash["id"], "debit": 1000}, {"account_id": liability["id"], "credit": 1000}])
    bs = client.get(f"/api/accounting/reports/balance-sheet?business_id={business['id']}&as_of=2026-12-31").get_json()
    assert bs["total_assets"] == 3000
    assert bs["total_liabilities"] == 1000
    assert bs["total_equity"] == 2000
    assert bs["current_earnings"] == 0
    assert bs["balanced"] is True


def test_balance_sheet_includes_current_earnings(client):
    business, cash, _, revenue, expense, _, equity = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 5000}, {"account_id": equity["id"], "credit": 5000}])
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 2000}, {"account_id": revenue["id"], "credit": 2000}])
    _entry(client, business["id"], "2026-03-15", "Cost", [{"account_id": expense["id"], "debit": 500}, {"account_id": cash["id"], "credit": 500}])
    bs = client.get(f"/api/accounting/reports/balance-sheet?business_id={business['id']}&as_of=2026-12-31").get_json()
    assert bs["current_earnings"] == 1500
    assert bs["total_equity"] == 6500
    assert bs["total_assets"] == 6500
    assert bs["balanced"] is True


def test_balance_sheet_date_filtering(client):
    business, cash, _, _, _, _, equity = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 1000}, {"account_id": equity["id"], "credit": 1000}])
    _entry(client, business["id"], "2026-06-01", "More capital", [{"account_id": cash["id"], "debit": 2000}, {"account_id": equity["id"], "credit": 2000}])
    bs = client.get(f"/api/accounting/reports/balance-sheet?business_id={business['id']}&as_of=2026-03-31").get_json()
    assert bs["total_assets"] == 1000
    assert bs["total_equity"] == 1000
    assert bs["balanced"] is True


def test_draft_entries_excluded_from_reports(client):
    business, cash, _, revenue, _, _, _ = _setup(client)
    _entry(client, business["id"], "2026-01-10", "Posted sale", [{"account_id": cash["id"], "debit": 400}, {"account_id": revenue["id"], "credit": 400}])
    _entry(client, business["id"], "2026-01-15", "Draft sale", [{"account_id": cash["id"], "debit": 999}, {"account_id": revenue["id"], "credit": 999}], status="draft")
    pl = client.get(f"/api/accounting/reports/profit-loss?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert pl["total_revenue"] == 400
    bs = client.get(f"/api/accounting/reports/balance-sheet?business_id={business['id']}&as_of=2026-12-31").get_json()
    assert bs["total_assets"] == 400


def test_reports_are_isolated_per_business(client):
    first, cash1, _, revenue1, _, _, _ = _setup(client, "First LLC")
    second, cash2, _, revenue2, _, _, _ = _setup(client, "Second LLC")
    _entry(client, first["id"], "2026-01-10", "Sale 1", [{"account_id": cash1["id"], "debit": 700}, {"account_id": revenue1["id"], "credit": 700}])
    _entry(client, second["id"], "2026-01-10", "Sale 2", [{"account_id": cash2["id"], "debit": 300}, {"account_id": revenue2["id"], "credit": 300}])
    pl1 = client.get(f"/api/accounting/reports/profit-loss?business_id={first['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    pl2 = client.get(f"/api/accounting/reports/profit-loss?business_id={second['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert pl1["total_revenue"] == 700
    assert pl2["total_revenue"] == 300


def test_invalid_date_range_rejected(client):
    business, _, _, _, _, _, _ = _setup(client)
    response = client.get(f"/api/accounting/reports/profit-loss?business_id={business['id']}&start_date=2026-12-31&end_date=2026-01-01")
    assert response.status_code == 400


def test_reports_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/profit-loss?business_id=1").status_code == 401
    assert client.get("/api/accounting/reports/balance-sheet?business_id=1").status_code == 401
    assert client.get("/api/accounting/reports/corporate-tax?business_id=1").status_code == 401


def test_corporate_tax_summary_uses_accounting_net_income(client):
    business, cash, _, revenue, expense, _, _ = _setup(client)
    _entry(client, business["id"], "2026-02-01", "Sale", [{"account_id": cash["id"], "debit": 10000}, {"account_id": revenue["id"], "credit": 10000}])
    _entry(client, business["id"], "2026-02-15", "Cost", [{"account_id": expense["id"], "debit": 4000}, {"account_id": cash["id"], "credit": 4000}])
    ct = client.get(f"/api/accounting/reports/corporate-tax?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert ct["total_revenue"] == 10000
    assert ct["total_expenses"] == 4000
    assert ct["net_income"] == 6000
    assert ct["taxable_income"] == 6000
    assert ct["federal_tax_estimate"] == 1260
    assert ct["rate"] == 0.21


def test_corporate_tax_zero_when_net_loss(client):
    business, cash, _, revenue, expense, _, _ = _setup(client)
    _entry(client, business["id"], "2026-02-01", "Sale", [{"account_id": cash["id"], "debit": 1000}, {"account_id": revenue["id"], "credit": 1000}])
    _entry(client, business["id"], "2026-02-15", "Big cost", [{"account_id": expense["id"], "debit": 3000}, {"account_id": cash["id"], "credit": 3000}])
    ct = client.get(f"/api/accounting/reports/corporate-tax?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert ct["net_income"] == -2000
    assert ct["taxable_income"] == 0
    assert ct["federal_tax_estimate"] == 0
