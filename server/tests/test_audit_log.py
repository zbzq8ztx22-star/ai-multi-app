from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def test_audit_log_records_accounting_writes(client):
    business = _business(client, "Audit LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    _entry(client, business["id"], "2026-01-01", "Capital contribution", [{"account_id": cash["id"], "debit": 5000}, {"account_id": equity["id"], "credit": 5000}])
    log = client.get("/api/audit/log").get_json()
    assert len(log) >= 1
    entry = log[0]
    assert entry["module"] == "accounting"
    assert entry["action"] == "create"
    assert entry["username"] == "testuser"
    assert "Capital contribution" in entry["description"]


def test_audit_log_records_budget_operations(client):
    business = _business(client, "Budget Audit LLC")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    budget = client.post("/api/accounting/budgets", json={
        "business_id": business["id"], "account_id": revenue["id"], "fiscal_year": 2026,
        "period": "annual", "budgeted_amount": 10000,
    }).get_json()
    client.put(f"/api/accounting/budgets/{budget['id']}", json={"budgeted_amount": 15000})
    client.delete(f"/api/accounting/budgets/{budget['id']}")
    log = client.get("/api/audit/log").get_json()
    actions = [e["action"] for e in log if e["entity_type"] == "budget"]
    assert "create" in actions
    assert "update" in actions
    assert "delete" in actions


def test_audit_log_filter_by_module(client):
    business = _business(client, "Filter LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    _entry(client, business["id"], "2026-01-01", "Test", [{"account_id": cash["id"], "debit": 100}, {"account_id": equity["id"], "credit": 100}])
    log = client.get("/api/audit/log?module=accounting").get_json()
    assert all(e["module"] == "accounting" for e in log)
    assert len(log) >= 1


def test_audit_log_requires_admin(app):
    client = app.test_client()
    client.post("/api/auth/register", json={"username": "viewer1", "password": "pass1234", "role": "viewer"})
    client.post("/api/auth/login", json={"username": "viewer1", "password": "pass1234"})
    assert client.get("/api/audit/log").status_code == 403


def test_audit_log_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/audit/log").status_code == 401


def test_audit_log_limit(client):
    business = _business(client, "Limit LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    for i in range(5):
        _entry(client, business["id"], "2026-01-01", f"Entry {i}", [{"account_id": cash["id"], "debit": 10}, {"account_id": equity["id"], "credit": 10}])
    log = client.get("/api/audit/log?limit=3").get_json()
    assert len(log) == 3
