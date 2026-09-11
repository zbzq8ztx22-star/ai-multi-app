import datetime

from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _setup(client, name="Trends LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Expenses", "expense")
    return business, cash, revenue, expense


def test_trends_returns_months(client):
    business, cash, revenue, expense = _setup(client)
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()
    _entry(client, business["id"], month_start, "Sale", [{"account_id": cash["id"], "debit": 1000}, {"account_id": revenue["id"], "credit": 1000}])
    trends = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=3").get_json()
    assert len(trends["months"]) == 3
    assert "revenue" in trends["months"][0]
    assert "expenses" in trends["months"][0]
    assert "net_income" in trends["months"][0]
    assert "changes" in trends


def test_trends_revenue_calculated(client):
    business, cash, revenue, expense = _setup(client)
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()
    _entry(client, business["id"], month_start, "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    trends = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=3").get_json()
    current_month = trends["months"][-1]
    assert current_month["revenue"] == 5000
    assert current_month["net_income"] == 5000


def test_trends_expenses_calculated(client):
    business, cash, revenue, expense = _setup(client)
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()
    _entry(client, business["id"], month_start, "Rent", [{"account_id": expense["id"], "debit": 2000}, {"account_id": cash["id"], "credit": 2000}])
    trends = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=3").get_json()
    current_month = trends["months"][-1]
    assert current_month["expenses"] == 2000
    assert current_month["net_income"] == -2000


def test_trends_net_income(client):
    business, cash, revenue, expense = _setup(client)
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()
    _entry(client, business["id"], month_start, "Sale", [{"account_id": cash["id"], "debit": 3000}, {"account_id": revenue["id"], "credit": 3000}])
    _entry(client, business["id"], month_start, "Rent", [{"account_id": expense["id"], "debit": 1000}, {"account_id": cash["id"], "credit": 1000}])
    trends = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=3").get_json()
    current_month = trends["months"][-1]
    assert current_month["revenue"] == 3000
    assert current_month["expenses"] == 1000
    assert current_month["net_income"] == 2000


def test_trends_excludes_draft_entries(client):
    business, cash, revenue, expense = _setup(client)
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()
    response = client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": month_start, "description": "Draft sale",
        "status": "draft", "lines": [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}],
    })
    assert response.status_code == 201
    trends = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=3").get_json()
    current_month = trends["months"][-1]
    assert current_month["revenue"] == 0


def test_trends_changes_calculated(client):
    business, cash, revenue, expense = _setup(client)
    today = datetime.date.today()
    # This month
    this_month = today.replace(day=1).isoformat()
    _entry(client, business["id"], this_month, "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    # Last month
    if today.month == 1:
        prev = today.replace(year=today.year - 1, month=12, day=1)
    else:
        prev = today.replace(month=today.month - 1, day=1)
    prev_month = prev.isoformat()
    _entry(client, business["id"], prev_month, "Sale", [{"account_id": cash["id"], "debit": 3000}, {"account_id": revenue["id"], "credit": 3000}])
    trends = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=3").get_json()
    assert trends["changes"]["revenue"] == 2000


def test_trends_empty_business(client):
    business = _business(client, "Empty Trends LLC")
    trends = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=3").get_json()
    assert len(trends["months"]) == 3
    assert all(m["revenue"] == 0 for m in trends["months"])


def test_trends_isolated_per_business(client):
    first, cash1, rev1, _ = _setup(client, "First Trends LLC")
    second, cash2, rev2, _ = _setup(client, "Second Trends LLC")
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()
    _entry(client, first["id"], month_start, "Sale", [{"account_id": cash1["id"], "debit": 1000}, {"account_id": rev1["id"], "credit": 1000}])
    t1 = client.get(f"/api/dashboard/trends?business_id={first['id']}&months=3").get_json()
    t2 = client.get(f"/api/dashboard/trends?business_id={second['id']}&months=3").get_json()
    assert t1["months"][-1]["revenue"] == 1000
    assert t2["months"][-1]["revenue"] == 0


def test_trends_invalid_months(client):
    business = _business(client, "Bad Months LLC")
    response = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=0")
    assert response.status_code == 400
    response = client.get(f"/api/dashboard/trends?business_id={business['id']}&months=50")
    assert response.status_code == 400


def test_trends_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/dashboard/trends?business_id=1").status_code == 401
