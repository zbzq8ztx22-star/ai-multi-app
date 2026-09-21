from .test_accounting import _account, _business


def _setup(client, name="Recurring LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    expense = _account(client, business["id"], "6000", "Rent", "expense")
    return business, cash, expense


def test_create_recurring_expense(client):
    business, cash, expense = _setup(client)
    rec = client.post("/api/accounting/recurring-expenses", json={
        "business_id": business["id"], "description": "Monthly rent",
        "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"],
        "frequency": "monthly", "start_date": "2026-01-01",
    }).get_json()
    assert rec["description"] == "Monthly rent"
    assert rec["amount"] == 2000
    assert rec["frequency"] == "monthly"
    assert rec["next_date"] == "2026-01-01"
    assert rec["active"] == 1


def test_list_recurring_expenses(client):
    business, cash, expense = _setup(client)
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-01"})
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Insurance", "amount": 500, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "yearly", "start_date": "2026-01-01"})
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    assert len(recs) == 2


def test_create_recurring_invalid_frequency(client):
    business, cash, expense = _setup(client)
    response = client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Test", "amount": 100, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "daily", "start_date": "2026-01-01"})
    assert response.status_code == 400


def test_create_recurring_invalid_amount(client):
    business, cash, expense = _setup(client)
    response = client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Test", "amount": -100, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-01"})
    assert response.status_code == 400


def test_update_recurring_expense(client):
    business, cash, expense = _setup(client)
    rec = client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-01"}).get_json()
    response = client.put(f"/api/accounting/recurring-expenses/{rec['id']}", json={"amount": 2500, "active": False})
    assert response.status_code == 200
    assert response.get_json()["amount"] == 2500
    assert response.get_json()["active"] == 0


def test_delete_recurring_expense(client):
    business, cash, expense = _setup(client)
    rec = client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-01"}).get_json()
    response = client.delete(f"/api/accounting/recurring-expenses/{rec['id']}")
    assert response.status_code == 200
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    assert len(recs) == 0


def test_post_due_recurring_expenses(client):
    business, cash, expense = _setup(client)
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-01"})
    result = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of=2026-02-15").get_json()
    assert result["posted_count"] == 1
    # After posting, next_date should advance to 2026-02-01
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    assert recs[0]["next_date"] == "2026-02-01"
    assert recs[0]["last_posted_date"] == "2026-01-01"
    # Expenses should be created
    expenses = client.get(f"/api/accounting/expenses?business_id={business['id']}").get_json()
    assert len(expenses) == 1
    assert expenses[0]["description"] == "Rent"


def test_post_due_skips_inactive(client):
    business, cash, expense = _setup(client)
    rec = client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-01"}).get_json()
    client.put(f"/api/accounting/recurring-expenses/{rec['id']}", json={"active": False})
    result = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of=2026-02-15").get_json()
    assert result["posted_count"] == 0


def test_post_due_respects_end_date(client):
    business, cash, expense = _setup(client)
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-01", "end_date": "2026-01-15"})
    result = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of=2026-03-01").get_json()
    assert result["posted_count"] == 1
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    assert recs[0]["active"] == 0


def test_post_due_month_end_jan_31(client):
    business, cash, expense = _setup(client, "MonthEnd Jan LLC")
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-31"})
    result = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of=2026-02-15").get_json()
    assert result["posted_count"] == 1
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    # Jan 31 + 1 month must clamp to the last day of February (non-leap year)
    assert recs[0]["next_date"] == "2026-02-28"
    expenses = client.get(f"/api/accounting/expenses?business_id={business['id']}").get_json()
    assert expenses[0]["expense_date"] == "2026-01-31"


def test_post_due_month_end_mar_31(client):
    business, cash, expense = _setup(client, "MonthEnd Mar LLC")
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-03-31"})
    result = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of=2026-04-15").get_json()
    assert result["posted_count"] == 1
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    # Mar 31 + 1 month must clamp to Apr 30
    assert recs[0]["next_date"] == "2026-04-30"


def test_post_due_leap_year_feb_29(client):
    business, cash, expense = _setup(client, "Leap LLC")
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Lease", "amount": 3000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "yearly", "start_date": "2024-02-29"})
    result = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of=2024-03-15").get_json()
    assert result["posted_count"] == 1
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    # 2024-02-29 + 1 year must clamp to 2025-02-28 (2025 is not a leap year)
    assert recs[0]["next_date"] == "2025-02-28"


def test_post_due_rolls_back_on_posting_failure(client):
    business, cash, expense = _setup(client, "Atomic LLC")
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-01-31"})
    # Close the period covering next_date so posting fails inside the transaction
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-01-31"})
    response = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of=2026-02-15")
    assert response.status_code == 400
    # The expense insert and the next_date advance must roll back together
    expenses = client.get(f"/api/accounting/expenses?business_id={business['id']}").get_json()
    assert len(expenses) == 0
    recs = client.get(f"/api/accounting/recurring-expenses?business_id={business['id']}").get_json()
    assert recs[0]["next_date"] == "2026-01-31"
    assert recs[0]["last_posted_date"] is None
    assert recs[0]["active"] == 1


def test_recurring_isolated_per_business(client):
    first, cash1, exp1 = _setup(client, "First LLC")
    second, cash2, exp2 = _setup(client, "Second LLC")
    client.post("/api/accounting/recurring-expenses", json={"business_id": first["id"], "description": "Rent", "amount": 1000, "expense_account_id": exp1["id"], "payment_account_id": cash1["id"], "frequency": "monthly", "start_date": "2026-01-01"})
    r1 = client.get(f"/api/accounting/recurring-expenses?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/recurring-expenses?business_id={second['id']}").get_json()
    assert len(r1) == 1
    assert len(r2) == 0


def test_recurring_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/recurring-expenses?business_id=1").status_code == 401
    assert client.post("/api/accounting/recurring-expenses", json={}).status_code == 401
