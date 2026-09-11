from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })


def _setup(client, name="Budget Alert LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    expense = _account(client, business["id"], "6000", "Office Expense", "expense")
    return business, cash, expense


def _create_budget(client, business_id, account_id, fiscal_year, period, amount):
    return client.post("/api/accounting/budgets", json={
        "business_id": business_id, "account_id": account_id,
        "fiscal_year": fiscal_year, "period": period, "budgeted_amount": amount,
    }).get_json()


def test_budget_alerts_no_budgets(client):
    business, _, _ = _setup(client)
    result = client.get(f"/api/accounting/budgets/alerts?business_id={business['id']}&fiscal_year=2026").get_json()
    assert result["alerts"] == []
    assert result["total_budget"] == 0


def test_budget_alerts_under_threshold(client):
    business, cash, expense = _setup(client)
    _create_budget(client, business["id"], expense["id"], 2026, "annual", 10000)
    _entry(client, business["id"], "2026-06-01", "Expense", [{"account_id": expense["id"], "debit": 3000}, {"account_id": cash["id"], "credit": 3000}])
    result = client.get(f"/api/accounting/budgets/alerts?business_id={business['id']}&fiscal_year=2026").get_json()
    assert len(result["alerts"]) == 0
    assert result["total_budget"] == 10000
    assert result["total_actual"] == 3000


def test_budget_alerts_approaching(client):
    business, cash, expense = _setup(client)
    _create_budget(client, business["id"], expense["id"], 2026, "annual", 10000)
    _entry(client, business["id"], "2026-06-01", "Expense", [{"account_id": expense["id"], "debit": 8500}, {"account_id": cash["id"], "credit": 8500}])
    result = client.get(f"/api/accounting/budgets/alerts?business_id={business['id']}&fiscal_year=2026").get_json()
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["alert_level"] == "approaching"
    assert result["alerts"][0]["percent_used"] == 85.0


def test_budget_alerts_over_budget(client):
    business, cash, expense = _setup(client)
    _create_budget(client, business["id"], expense["id"], 2026, "annual", 5000)
    _entry(client, business["id"], "2026-06-01", "Expense", [{"account_id": expense["id"], "debit": 7000}, {"account_id": cash["id"], "credit": 7000}])
    result = client.get(f"/api/accounting/budgets/alerts?business_id={business['id']}&fiscal_year=2026").get_json()
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["alert_level"] == "over_budget"
    assert result["alerts"][0]["variance"] == -2000


def test_budget_alerts_custom_threshold(client):
    business, cash, expense = _setup(client)
    _create_budget(client, business["id"], expense["id"], 2026, "annual", 10000)
    _entry(client, business["id"], "2026-06-01", "Expense", [{"account_id": expense["id"], "debit": 5000}, {"account_id": cash["id"], "credit": 5000}])
    # With 40% threshold, 50% usage should trigger "approaching"
    result = client.get(f"/api/accounting/budgets/alerts?business_id={business['id']}&fiscal_year=2026&threshold_percent=40").get_json()
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["alert_level"] == "approaching"


def test_budget_alerts_multiple_accounts(client):
    business, cash, expense = _setup(client)
    expense2 = _account(client, business["id"], "6100", "Rent", "expense")
    _create_budget(client, business["id"], expense["id"], 2026, "annual", 5000)
    _create_budget(client, business["id"], expense2["id"], 2026, "annual", 8000)
    _entry(client, business["id"], "2026-06-01", "Office", [{"account_id": expense["id"], "debit": 6000}, {"account_id": cash["id"], "credit": 6000}])
    _entry(client, business["id"], "2026-06-01", "Rent", [{"account_id": expense2["id"], "debit": 4000}, {"account_id": cash["id"], "credit": 4000}])
    result = client.get(f"/api/accounting/budgets/alerts?business_id={business['id']}&fiscal_year=2026").get_json()
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["account_code"] == "6000"  # over budget first
    assert result["total_budget"] == 13000
    assert result["total_actual"] == 10000


def test_budget_alerts_invalid_threshold(client):
    business, _, _ = _setup(client)
    response = client.get(f"/api/accounting/budgets/alerts?business_id={business['id']}&fiscal_year=2026&threshold_percent=150")
    assert response.status_code == 400


def test_budget_alerts_isolated_per_business(client):
    first, cash1, exp1 = _setup(client, "First BA LLC")
    second, cash2, exp2 = _setup(client, "Second BA LLC")
    _create_budget(client, first["id"], exp1["id"], 2026, "annual", 5000)
    _entry(client, first["id"], "2026-06-01", "Expense", [{"account_id": exp1["id"], "debit": 6000}, {"account_id": cash1["id"], "credit": 6000}])
    r1 = client.get(f"/api/accounting/budgets/alerts?business_id={first['id']}&fiscal_year=2026").get_json()
    r2 = client.get(f"/api/accounting/budgets/alerts?business_id={second['id']}&fiscal_year=2026").get_json()
    assert len(r1["alerts"]) == 1
    assert len(r2["alerts"]) == 0


def test_budget_alerts_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/budgets/alerts?business_id=1&fiscal_year=2026").status_code == 401
