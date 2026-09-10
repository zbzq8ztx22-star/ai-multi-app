from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _setup(client, name="KPI LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    inventory = _account(client, business["id"], "1200", "Inventory", "asset")
    liability = _account(client, business["id"], "2000", "Loan Payable", "liability")
    equity = _account(client, business["id"], "3000", "Owner Equity", "equity")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Operating Expense", "expense")
    return business, cash, inventory, liability, equity, revenue, expense


def test_kpis_with_profitable_business(client):
    business, cash, _, liability, equity, revenue, expense = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 10000}, {"account_id": equity["id"], "credit": 10000}])
    _entry(client, business["id"], "2026-01-01", "Loan", [{"account_id": cash["id"], "debit": 5000}, {"account_id": liability["id"], "credit": 5000}])
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 8000}, {"account_id": revenue["id"], "credit": 8000}])
    _entry(client, business["id"], "2026-03-15", "Cost", [{"account_id": expense["id"], "debit": 3000}, {"account_id": cash["id"], "credit": 3000}])
    kpis = client.get(f"/api/accounting/reports/kpis?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert kpis["total_assets"] == 20000
    assert kpis["total_liabilities"] == 5000
    assert kpis["total_equity"] == 15000
    assert kpis["total_revenue"] == 8000
    assert kpis["net_income"] == 5000
    assert kpis["current_ratio"] == 4.0
    assert kpis["debt_to_equity"] == round(5000 / 15000, 2)
    assert kpis["profit_margin_pct"] == round((5000 / 8000) * 100, 2)
    assert kpis["return_on_equity_pct"] == round((5000 / 15000) * 100, 2)
    assert kpis["asset_turnover"] == round(8000 / 20000, 2)


def test_kpis_with_zero_liabilities(client):
    business, cash, _, _, equity, revenue, _ = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 5000}, {"account_id": equity["id"], "credit": 5000}])
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 2000}, {"account_id": revenue["id"], "credit": 2000}])
    kpis = client.get(f"/api/accounting/reports/kpis?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert kpis["total_liabilities"] == 0
    assert kpis["current_ratio"] is None
    assert kpis["debt_to_equity"] == 0.0


def test_kpis_with_zero_revenue(client):
    business, cash, _, _, equity, _, expense = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 5000}, {"account_id": equity["id"], "credit": 5000}])
    _entry(client, business["id"], "2026-03-01", "Cost", [{"account_id": expense["id"], "debit": 1000}, {"account_id": cash["id"], "credit": 1000}])
    kpis = client.get(f"/api/accounting/reports/kpis?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert kpis["total_revenue"] == 0
    assert kpis["profit_margin_pct"] is None
    assert kpis["asset_turnover"] == 0.0


def test_kpis_empty_business(client):
    business = _business(client, "Empty LLC")
    kpis = client.get(f"/api/accounting/reports/kpis?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert kpis["total_assets"] == 0
    assert kpis["total_liabilities"] == 0
    assert kpis["total_equity"] == 0
    assert kpis["current_ratio"] is None
    assert kpis["debt_to_equity"] is None


def test_kpis_isolated_per_business(client):
    first, cash1, _, _, eq1, rev1, _ = _setup(client, "First LLC")
    second, cash2, _, _, eq2, rev2, _ = _setup(client, "Second LLC")
    _entry(client, first["id"], "2026-01-01", "Capital", [{"account_id": cash1["id"], "debit": 10000}, {"account_id": eq1["id"], "credit": 10000}])
    _entry(client, first["id"], "2026-03-01", "Sale", [{"account_id": cash1["id"], "debit": 5000}, {"account_id": rev1["id"], "credit": 5000}])
    _entry(client, second["id"], "2026-01-01", "Capital", [{"account_id": cash2["id"], "debit": 2000}, {"account_id": eq2["id"], "credit": 2000}])
    k1 = client.get(f"/api/accounting/reports/kpis?business_id={first['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    k2 = client.get(f"/api/accounting/reports/kpis?business_id={second['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert k1["total_revenue"] == 5000
    assert k2["total_revenue"] == 0


def test_kpis_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/kpis?business_id=1&start_date=2026-01-01&end_date=2026-12-31").status_code == 401
