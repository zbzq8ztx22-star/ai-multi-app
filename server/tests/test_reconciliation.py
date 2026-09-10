from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _setup(client, name="Recon LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    return business, cash, revenue


def test_create_reconciliation_matched(client):
    business, cash, revenue = _setup(client)
    _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    recon = client.post("/api/accounting/reconciliations", json={
        "business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-01-31",
        "statement_balance": 5000, "notes": "Bank statement",
    }).get_json()
    assert recon["book_balance"] == 5000
    assert recon["difference"] == 0
    assert recon["status"] == "reconciled"


def test_create_reconciliation_with_discrepancy(client):
    business, cash, revenue = _setup(client)
    _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    recon = client.post("/api/accounting/reconciliations", json={
        "business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-01-31",
        "statement_balance": 4800,
    }).get_json()
    assert recon["book_balance"] == 5000
    assert recon["difference"] == -200
    assert recon["status"] == "discrepancy"


def test_list_reconciliations(client):
    business, cash, revenue = _setup(client)
    _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    client.post("/api/accounting/reconciliations", json={"business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-01-31", "statement_balance": 5000})
    recons = client.get(f"/api/accounting/reconciliations?business_id={business['id']}").get_json()
    assert len(recons) == 1
    assert recons[0]["account_code"] == "1000"


def test_update_reconciliation_status(client):
    business, cash, _ = _setup(client)
    recon = client.post("/api/accounting/reconciliations", json={"business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-01-31", "statement_balance": 0}).get_json()
    response = client.put(f"/api/accounting/reconciliations/{recon['id']}", json={"status": "reconciled", "notes": "Fixed"})
    assert response.status_code == 200
    assert response.get_json()["status"] == "reconciled"
    assert response.get_json()["notes"] == "Fixed"


def test_update_reconciliation_invalid_status(client):
    business, cash, _ = _setup(client)
    recon = client.post("/api/accounting/reconciliations", json={"business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-01-31", "statement_balance": 0}).get_json()
    response = client.put(f"/api/accounting/reconciliations/{recon['id']}", json={"status": "invalid"})
    assert response.status_code == 400


def test_delete_reconciliation(client):
    business, cash, _ = _setup(client)
    recon = client.post("/api/accounting/reconciliations", json={"business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-01-31", "statement_balance": 0}).get_json()
    response = client.delete(f"/api/accounting/reconciliations/{recon['id']}")
    assert response.status_code == 200
    recons = client.get(f"/api/accounting/reconciliations?business_id={business['id']}").get_json()
    assert len(recons) == 0


def test_reconciliation_invalid_account(client):
    business, _, _ = _setup(client)
    other = _business(client, "Other LLC")
    other_cash = _account(client, other["id"], "1000", "Cash", "asset")
    response = client.post("/api/accounting/reconciliations", json={"business_id": business["id"], "account_id": other_cash["id"], "statement_date": "2026-01-31", "statement_balance": 0})
    assert response.status_code == 400


def test_reconciliation_isolated_per_business(client):
    first, cash1, _ = _setup(client, "First LLC")
    second, cash2, _ = _setup(client, "Second LLC")
    client.post("/api/accounting/reconciliations", json={"business_id": first["id"], "account_id": cash1["id"], "statement_date": "2026-01-31", "statement_balance": 0})
    r1 = client.get(f"/api/accounting/reconciliations?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/reconciliations?business_id={second['id']}").get_json()
    assert len(r1) == 1
    assert len(r2) == 0


def test_reconciliation_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reconciliations?business_id=1").status_code == 401
    assert client.post("/api/accounting/reconciliations", json={}).status_code == 401


def test_reconciliation_book_balance_from_posted_only(client):
    business, cash, revenue = _setup(client)
    _entry(client, business["id"], "2026-01-15", "Posted", [{"account_id": cash["id"], "debit": 3000}, {"account_id": revenue["id"], "credit": 3000}])
    _entry(client, business["id"], "2026-01-20", "Draft", [{"account_id": cash["id"], "debit": 9999}, {"account_id": revenue["id"], "credit": 9999}], status="draft")
    recon = client.post("/api/accounting/reconciliations", json={"business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-01-31", "statement_balance": 3000}).get_json()
    assert recon["book_balance"] == 3000
    assert recon["status"] == "reconciled"
