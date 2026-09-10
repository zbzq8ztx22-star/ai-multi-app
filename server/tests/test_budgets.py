from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _setup(client, name="Budget LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Office Expense", "expense")
    return business, cash, revenue, expense


def _budget(client, business_id, account_id, fiscal_year, amount):
    response = client.post("/api/accounting/budgets", json={
        "business_id": business_id, "account_id": account_id, "fiscal_year": fiscal_year,
        "period": "annual", "budgeted_amount": amount,
    })
    assert response.status_code == 201
    return response.get_json()


def test_create_and_list_budget(client):
    business, _, revenue, expense = _setup(client)
    _budget(client, business["id"], revenue["id"], 2026, 50000)
    _budget(client, business["id"], expense["id"], 2026, 30000)
    budgets = client.get(f"/api/accounting/budgets?business_id={business['id']}&fiscal_year=2026").get_json()
    assert len(budgets) == 2
    assert budgets[0]["account_code"] == "4000"


def test_duplicate_budget_rejected(client):
    business, _, revenue, _ = _setup(client)
    _budget(client, business["id"], revenue["id"], 2026, 50000)
    response = client.post("/api/accounting/budgets", json={
        "business_id": business["id"], "account_id": revenue["id"], "fiscal_year": 2026,
        "period": "annual", "budgeted_amount": 60000,
    })
    assert response.status_code == 400


def test_update_budget(client):
    business, _, revenue, _ = _setup(client)
    budget = _budget(client, business["id"], revenue["id"], 2026, 50000)
    response = client.put(f"/api/accounting/budgets/{budget['id']}", json={"budgeted_amount": 75000})
    assert response.status_code == 200
    assert response.get_json()["budgeted_amount"] == 75000


def test_delete_budget(client):
    business, _, revenue, _ = _setup(client)
    budget = _budget(client, business["id"], revenue["id"], 2026, 50000)
    response = client.delete(f"/api/accounting/budgets/{budget['id']}")
    assert response.status_code == 200
    budgets = client.get(f"/api/accounting/budgets?business_id={business['id']}&fiscal_year=2026").get_json()
    assert len(budgets) == 0


def test_budget_vs_actual_revenue(client):
    business, cash, revenue, _ = _setup(client)
    _budget(client, business["id"], revenue["id"], 2026, 50000)
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 35000}, {"account_id": revenue["id"], "credit": 35000}])
    report = client.get(f"/api/accounting/reports/budget-vs-actual?business_id={business['id']}&fiscal_year=2026").get_json()
    assert len(report["lines"]) == 1
    line = report["lines"][0]
    assert line["budgeted"] == 50000
    assert line["actual"] == 35000
    assert line["variance"] == 15000
    assert line["over_budget"] is False


def test_budget_vs_actual_expense(client):
    business, cash, _, expense = _setup(client)
    _budget(client, business["id"], expense["id"], 2026, 20000)
    _entry(client, business["id"], "2026-03-01", "Cost", [{"account_id": expense["id"], "debit": 25000}, {"account_id": cash["id"], "credit": 25000}])
    report = client.get(f"/api/accounting/reports/budget-vs-actual?business_id={business['id']}&fiscal_year=2026").get_json()
    line = report["lines"][0]
    assert line["budgeted"] == 20000
    assert line["actual"] == 25000
    assert line["variance"] == -5000
    assert line["over_budget"] is True


def test_budget_vs_actual_excludes_draft_entries(client):
    business, cash, revenue, _ = _setup(client)
    _budget(client, business["id"], revenue["id"], 2026, 50000)
    _entry(client, business["id"], "2026-03-01", "Posted", [{"account_id": cash["id"], "debit": 10000}, {"account_id": revenue["id"], "credit": 10000}])
    _entry(client, business["id"], "2026-03-02", "Draft", [{"account_id": cash["id"], "debit": 99999}, {"account_id": revenue["id"], "credit": 99999}], status="draft")
    report = client.get(f"/api/accounting/reports/budget-vs-actual?business_id={business['id']}&fiscal_year=2026").get_json()
    assert report["lines"][0]["actual"] == 10000


def test_budget_vs_actual_empty_when_no_budgets(client):
    business, cash, revenue, _ = _setup(client)
    _entry(client, business["id"], "2026-03-01", "Sale", [{"account_id": cash["id"], "debit": 10000}, {"account_id": revenue["id"], "credit": 10000}])
    report = client.get(f"/api/accounting/reports/budget-vs-actual?business_id={business['id']}&fiscal_year=2026").get_json()
    assert report["lines"] == []
    assert report["total_budgeted"] == 0


def test_budgets_isolated_per_business(client):
    first, _, revenue1, _ = _setup(client, "First LLC")
    second, _, revenue2, _ = _setup(client, "Second LLC")
    _budget(client, first["id"], revenue1["id"], 2026, 10000)
    _budget(client, second["id"], revenue2["id"], 2026, 20000)
    r1 = client.get(f"/api/accounting/reports/budget-vs-actual?business_id={first['id']}&fiscal_year=2026").get_json()
    r2 = client.get(f"/api/accounting/reports/budget-vs-actual?business_id={second['id']}&fiscal_year=2026").get_json()
    assert r1["total_budgeted"] == 10000
    assert r2["total_budgeted"] == 20000


def test_budgets_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/budgets?business_id=1").status_code == 401
    assert client.post("/api/accounting/budgets", json={}).status_code == 401
    assert client.get("/api/accounting/reports/budget-vs-actual?business_id=1&fiscal_year=2026").status_code == 401


def test_budget_requires_valid_account_for_business(client):
    business, _, _, _ = _setup(client)
    other = _business(client, "Other LLC")
    other_revenue = _account(client, other["id"], "4000", "Revenue", "revenue")
    response = client.post("/api/accounting/budgets", json={
        "business_id": business["id"], "account_id": other_revenue["id"], "fiscal_year": 2026,
        "period": "annual", "budgeted_amount": 1000,
    })
    assert response.status_code == 400
