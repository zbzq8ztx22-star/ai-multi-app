from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _setup(client, name="CF LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equipment = _account(client, business["id"], "1500", "Equipment", "asset")
    liability = _account(client, business["id"], "2000", "Loan Payable", "liability")
    equity = _account(client, business["id"], "3000", "Owner Equity", "equity")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Operating Expense", "expense")
    expense2 = _account(client, business["id"], "6100", "Rent", "expense")
    return business, cash, equipment, liability, equity, revenue, expense, expense2


def test_cash_flow_basic(client):
    business, cash, _, _, equity, revenue, expense, _ = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 10000}, {"account_id": equity["id"], "credit": 10000}])
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    _entry(client, business["id"], "2026-03-15", "Cost", [{"account_id": expense["id"], "debit": 2000}, {"account_id": cash["id"], "credit": 2000}])
    cf = client.get(f"/api/accounting/reports/cash-flow?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert cf["beginning_cash"] == 0
    assert cf["ending_cash"] == 13000
    assert cf["operating"]["net_income"] == 3000


def test_cash_flow_with_prior_period(client):
    business, cash, _, _, equity, revenue, expense, _ = _setup(client)
    _entry(client, business["id"], "2025-12-01", "Prior capital", [{"account_id": cash["id"], "debit": 5000}, {"account_id": equity["id"], "credit": 5000}])
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 3000}, {"account_id": revenue["id"], "credit": 3000}])
    cf = client.get(f"/api/accounting/reports/cash-flow?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert cf["beginning_cash"] == 5000
    assert cf["ending_cash"] == 8000


def test_cash_flow_invalid_dates(client):
    business, _, _, _, _, _, _, _ = _setup(client)
    response = client.get(f"/api/accounting/reports/cash-flow?business_id={business['id']}&start_date=2026-12-01&end_date=2026-01-01")
    assert response.status_code == 400


def test_cash_flow_empty_business(client):
    business = _business(client, "Empty CF LLC")
    cf = client.get(f"/api/accounting/reports/cash-flow?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert cf["beginning_cash"] == 0
    assert cf["ending_cash"] == 0
    assert cf["operating"]["net_income"] == 0


def test_expense_breakdown_by_account(client):
    business, cash, _, _, _, _, expense, expense2 = _setup(client)
    _entry(client, business["id"], "2026-03-01", "Opex", [{"account_id": expense["id"], "debit": 3000}, {"account_id": cash["id"], "credit": 3000}])
    _entry(client, business["id"], "2026-03-15", "Rent", [{"account_id": expense2["id"], "debit": 1000}, {"account_id": cash["id"], "credit": 1000}])
    bd = client.get(f"/api/accounting/reports/expense-breakdown?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert bd["total_expenses"] == 4000
    assert len(bd["breakdown"]) == 2
    assert bd["breakdown"][0]["amount"] == 3000
    assert bd["breakdown"][0]["percentage"] == 75.0
    assert bd["breakdown"][1]["percentage"] == 25.0


def test_expense_breakdown_empty(client):
    business = _business(client, "Empty BD LLC")
    bd = client.get(f"/api/accounting/reports/expense-breakdown?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31").get_json()
    assert bd["total_expenses"] == 0
    assert bd["breakdown"] == []


def test_multi_year_comparison(client):
    business, cash, _, _, _, revenue, expense, _ = _setup(client)
    _entry(client, business["id"], "2025-06-01", "2025 sale", [{"account_id": cash["id"], "debit": 10000}, {"account_id": revenue["id"], "credit": 10000}])
    _entry(client, business["id"], "2025-06-15", "2025 cost", [{"account_id": expense["id"], "debit": 4000}, {"account_id": cash["id"], "credit": 4000}])
    _entry(client, business["id"], "2026-06-01", "2026 sale", [{"account_id": cash["id"], "debit": 15000}, {"account_id": revenue["id"], "credit": 15000}])
    _entry(client, business["id"], "2026-06-15", "2026 cost", [{"account_id": expense["id"], "debit": 5000}, {"account_id": cash["id"], "credit": 5000}])
    comp = client.get(f"/api/accounting/reports/multi-year?business_id={business['id']}&years=2025,2026").get_json()
    assert len(comp["years"]) == 2
    y2025 = next(y for y in comp["years"] if y["year"] == 2025)
    y2026 = next(y for y in comp["years"] if y["year"] == 2026)
    assert y2025["total_revenue"] == 10000
    assert y2025["net_income"] == 6000
    assert y2026["total_revenue"] == 15000
    assert y2026["net_income"] == 10000


def test_multi_year_invalid_years(client):
    business = _business(client, "Bad Years LLC")
    response = client.get(f"/api/accounting/reports/multi-year?business_id={business['id']}&years=abc")
    assert response.status_code == 400


def test_multi_year_empty(client):
    business = _business(client, "Empty MY LLC")
    comp = client.get(f"/api/accounting/reports/multi-year?business_id={business['id']}&years=2025,2026").get_json()
    assert len(comp["years"]) == 2
    assert comp["years"][0]["total_revenue"] == 0


def test_new_reports_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/cash-flow?business_id=1").status_code == 401
    assert client.get("/api/accounting/reports/expense-breakdown?business_id=1").status_code == 401
    assert client.get("/api/accounting/reports/multi-year?business_id=1&years=2026").status_code == 401
