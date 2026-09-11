from .test_accounting import _account, _business


def _setup(client, name="Approval LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    expense = _account(client, business["id"], "6000", "Expense", "expense")
    return business, cash, expense


def _create_expense(client, business_id, date, amount, cash_id, expense_id, approval_status="approved"):
    return client.post("/api/accounting/expenses", json={
        "business_id": business_id, "expense_date": date, "amount": amount,
        "description": "Test expense", "payment_account_id": cash_id, "expense_account_id": expense_id,
        "approval_status": approval_status,
    }).get_json()


def test_create_pending_expense(client):
    business, cash, expense = _setup(client)
    exp = _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "pending")
    assert exp["approval_status"] == "pending"
    assert exp["journal_entry_id"] is None


def test_create_approved_expense_creates_entry(client):
    business, cash, expense = _setup(client)
    exp = _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "approved")
    assert exp["approval_status"] == "approved"
    assert exp["journal_entry_id"] is not None


def test_list_pending_expenses(client):
    business, cash, expense = _setup(client)
    _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "pending")
    _create_expense(client, business["id"], "2026-01-20", 300, cash["id"], expense["id"], "pending")
    _create_expense(client, business["id"], "2026-01-25", 200, cash["id"], expense["id"], "approved")
    pending = client.get(f"/api/accounting/expenses/pending?business_id={business['id']}").get_json()
    assert len(pending) == 2


def test_approve_expense(client):
    business, cash, expense = _setup(client)
    exp = _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "pending")
    result = client.put(f"/api/accounting/expenses/{exp['id']}/approve", json={"approver": "admin"})
    assert result.status_code == 200
    data = result.get_json()
    assert data["approval_status"] == "approved"
    assert data["journal_entry_id"] is not None
    assert data["approved_by"] == "admin"


def test_reject_expense(client):
    business, cash, expense = _setup(client)
    exp = _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "pending")
    result = client.put(f"/api/accounting/expenses/{exp['id']}/reject", json={"approver": "admin"})
    assert result.status_code == 200
    data = result.get_json()
    assert data["approval_status"] == "rejected"
    assert data["journal_entry_id"] is None


def test_approve_non_pending_rejected(client):
    business, cash, expense = _setup(client)
    exp = _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "approved")
    response = client.put(f"/api/accounting/expenses/{exp['id']}/approve", json={"approver": "admin"})
    assert response.status_code == 400


def test_reject_non_pending_rejected(client):
    business, cash, expense = _setup(client)
    exp = _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "approved")
    response = client.put(f"/api/accounting/expenses/{exp['id']}/reject", json={"approver": "admin"})
    assert response.status_code == 400


def test_approve_expense_balanced_entry(client):
    business, cash, expense = _setup(client)
    exp = _create_expense(client, business["id"], "2026-01-15", 500, cash["id"], expense["id"], "pending")
    client.put(f"/api/accounting/expenses/{exp['id']}/approve", json={"approver": "admin"})
    tb = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert tb["balanced"] is True


def test_pending_expenses_isolated_per_business(client):
    first, cash1, exp1 = _setup(client, "First Approval LLC")
    second, cash2, exp2 = _setup(client, "Second Approval LLC")
    _create_expense(client, first["id"], "2026-01-15", 500, cash1["id"], exp1["id"], "pending")
    p1 = client.get(f"/api/accounting/expenses/pending?business_id={first['id']}").get_json()
    p2 = client.get(f"/api/accounting/expenses/pending?business_id={second['id']}").get_json()
    assert len(p1) == 1
    assert len(p2) == 0


def test_expense_approval_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/expenses/pending?business_id=1").status_code == 401
