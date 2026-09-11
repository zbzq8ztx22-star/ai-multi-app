from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })


def _setup(client, name="Ratios LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    receivable = _account(client, business["id"], "1100", "AR", "asset")
    equipment = _account(client, business["id"], "1500", "Equipment", "asset")
    ap = _account(client, business["id"], "2000", "AP", "liability")
    loan = _account(client, business["id"], "2100", "Loan", "liability")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Expense", "expense")
    return business, cash, receivable, equipment, ap, loan, equity, revenue, expense


def test_financial_ratios_empty_business(client):
    business = _business(client, "Empty Ratios LLC")
    ratios = client.get(f"/api/accounting/reports/financial-ratios?business_id={business['id']}").get_json()
    assert ratios["balances"]["total_assets"] == 0
    assert ratios["current_ratio"] is None
    assert ratios["return_on_assets"] is None


def test_financial_ratios_with_balances(client):
    business, cash, _, _, ap, _, equity, revenue, expense = _setup(client)
    # Initial investment
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 10000}, {"account_id": equity["id"], "credit": 10000}])
    # Revenue
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    # Expense
    _entry(client, business["id"], "2026-03-15", "Rent", [{"account_id": expense["id"], "debit": 2000}, {"account_id": cash["id"], "credit": 2000}])
    ratios = client.get(f"/api/accounting/reports/financial-ratios?business_id={business['id']}").get_json()
    assert ratios["balances"]["total_assets"] == 13000
    assert ratios["balances"]["total_revenue"] == 5000
    assert ratios["balances"]["net_income"] == 3000
    assert ratios["profit_margin"] == 60.0


def test_financial_ratios_with_liabilities(client):
    business, cash, _, _, ap, loan, equity, _, _ = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 10000}, {"account_id": equity["id"], "credit": 10000}])
    _entry(client, business["id"], "2026-01-15", "Loan", [{"account_id": cash["id"], "debit": 5000}, {"account_id": loan["id"], "credit": 5000}])
    ratios = client.get(f"/api/accounting/reports/financial-ratios?business_id={business['id']}").get_json()
    assert ratios["balances"]["total_assets"] == 15000
    assert ratios["balances"]["total_liabilities"] == 5000
    assert ratios["balances"]["total_equity"] == 10000
    assert ratios["debt_ratio"] == round(5000 / 15000, 2)
    assert ratios["debt_to_equity"] == round(5000 / 10000, 2)


def test_financial_ratios_return_on_assets(client):
    business, cash, _, _, _, _, equity, revenue, expense = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 20000}, {"account_id": equity["id"], "credit": 20000}])
    _entry(client, business["id"], "2026-06-01", "Sale", [{"account_id": cash["id"], "debit": 8000}, {"account_id": revenue["id"], "credit": 8000}])
    _entry(client, business["id"], "2026-06-15", "Expense", [{"account_id": expense["id"], "debit": 3000}, {"account_id": cash["id"], "credit": 3000}])
    ratios = client.get(f"/api/accounting/reports/financial-ratios?business_id={business['id']}").get_json()
    assert ratios["balances"]["net_income"] == 5000
    assert ratios["balances"]["total_assets"] == 25000
    assert ratios["return_on_assets"] == round((5000 / 25000) * 100, 2)


def test_financial_ratios_as_of_date(client):
    business, cash, _, _, _, _, equity, revenue, _ = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 10000}, {"account_id": equity["id"], "credit": 10000}])
    _entry(client, business["id"], "2026-06-01", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    ratios = client.get(f"/api/accounting/reports/financial-ratios?business_id={business['id']}&as_of_date=2026-03-31").get_json()
    # Revenue entry is in June, should not be counted as of March
    assert ratios["balances"]["total_revenue"] == 0
    assert ratios["balances"]["total_assets"] == 10000


def test_financial_ratios_isolated_per_business(client):
    first, cash1, _, _, _, _, eq1, rev1, _ = _setup(client, "First Ratios LLC")
    second = _business(client, "Second Ratios LLC")
    cash2 = _account(client, second["id"], "1000", "Cash", "asset")
    eq2 = _account(client, second["id"], "3000", "Equity", "equity")
    _entry(client, first["id"], "2026-01-01", "Capital", [{"account_id": cash1["id"], "debit": 10000}, {"account_id": eq1["id"], "credit": 10000}])
    _entry(client, second["id"], "2026-01-01", "Capital", [{"account_id": cash2["id"], "debit": 5000}, {"account_id": eq2["id"], "credit": 5000}])
    r1 = client.get(f"/api/accounting/reports/financial-ratios?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/reports/financial-ratios?business_id={second['id']}").get_json()
    assert r1["balances"]["total_assets"] == 10000
    assert r2["balances"]["total_assets"] == 5000


def test_financial_ratios_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/financial-ratios?business_id=1").status_code == 401
