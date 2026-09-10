def _business(client, name="Ledger LLC"):
    return client.post("/api/entities/businesses", json={"legal_name": name, "entity_type": "llc"}).get_json()


def _account(client, business_id, code, name, account_type):
    response = client.post("/api/accounting/accounts", json={"business_id": business_id, "code": code, "name": name, "account_type": account_type})
    assert response.status_code == 201
    return response.get_json()


def test_chart_of_accounts_is_scoped_to_business(client):
    first = _business(client, "First LLC")
    second = _business(client, "Second LLC")
    _account(client, first["id"], "1000", "Cash", "asset")
    _account(client, second["id"], "1000", "Cash", "asset")
    first_accounts = client.get(f"/api/accounting/accounts?business_id={first['id']}").get_json()
    assert len(first_accounts) == 1
    assert first_accounts[0]["business_id"] == first["id"]


def test_duplicate_account_code_rejected(client):
    business = _business(client)
    _account(client, business["id"], "1000", "Cash", "asset")
    response = client.post("/api/accounting/accounts", json={"business_id": business["id"], "code": "1000", "name": "Bank", "account_type": "asset"})
    assert response.status_code == 400


def test_balanced_entry_updates_trial_balance_and_ledger(client):
    business = _business(client)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equity = _account(client, business["id"], "3000", "Owner Equity", "equity")
    response = client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-01-15", "reference": "CAP-1", "description": "Owner contribution",
        "lines": [{"account_id": cash["id"], "debit": 1000}, {"account_id": equity["id"], "credit": 1000}],
    })
    assert response.status_code == 201
    assert len(response.get_json()["lines"]) == 2
    balance = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert balance["balanced"] is True
    assert balance["total_debits"] == 1000
    assert balance["total_credits"] == 1000
    ledger = client.get(f"/api/accounting/ledger?business_id={business['id']}&account_id={cash['id']}").get_json()
    assert len(ledger) == 1
    assert ledger[0]["debit"] == 1000


def test_unbalanced_entry_rejected_without_partial_write(client):
    business = _business(client)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    response = client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-02-01", "description": "Bad entry",
        "lines": [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 99}],
    })
    assert response.status_code == 400
    assert client.get(f"/api/accounting/entries?business_id={business['id']}").get_json() == []


def test_account_from_another_business_rejected(client):
    first = _business(client, "First")
    second = _business(client, "Second")
    cash = _account(client, first["id"], "1000", "Cash", "asset")
    equity = _account(client, second["id"], "3000", "Equity", "equity")
    response = client.post("/api/accounting/entries", json={
        "business_id": first["id"], "entry_date": "2026-02-01", "description": "Cross company",
        "lines": [{"account_id": cash["id"], "debit": 50}, {"account_id": equity["id"], "credit": 50}],
    })
    assert response.status_code == 400


def test_accounting_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/accounts?business_id=1").status_code == 401
    assert client.post("/api/accounting/entries", json={}).status_code == 401
