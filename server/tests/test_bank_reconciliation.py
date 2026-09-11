from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    }).get_json()


def _setup(client, name="Bank Recon LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Checking", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Expense", "expense")
    return business, cash, revenue, expense


def test_create_bank_transaction(client):
    business, cash, _, _ = _setup(client)
    tx = client.post("/api/accounting/bank-transactions", json={
        "business_id": business["id"], "account_id": cash["id"],
        "transaction_date": "2026-01-15", "description": "Customer payment",
        "amount": 5000, "type": "deposit", "reference": "DEP-1",
    }).get_json()
    assert tx["amount"] == 5000
    assert tx["type"] == "deposit"
    assert tx["cleared"] == 0


def test_list_bank_transactions(client):
    business, cash, _, _ = _setup(client)
    client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-15", "amount": 5000, "type": "deposit"})
    client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-20", "amount": 1000, "type": "withdrawal"})
    txs = client.get(f"/api/accounting/bank-transactions?business_id={business['id']}").get_json()
    assert len(txs) == 2


def test_match_bank_transaction(client):
    business, cash, revenue, _ = _setup(client)
    entry = _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    tx = client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-15", "amount": 5000, "type": "deposit"}).get_json()
    journal_line_id = entry["lines"][0]["id"]
    result = client.put(f"/api/accounting/bank-transactions/{tx['id']}/match", json={"journal_line_id": journal_line_id}).get_json()
    assert result["cleared"] == 1
    assert result["matched_journal_line_id"] == journal_line_id


def test_unmatch_bank_transaction(client):
    business, cash, revenue, _ = _setup(client)
    entry = _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    tx = client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-15", "amount": 5000, "type": "deposit"}).get_json()
    client.put(f"/api/accounting/bank-transactions/{tx['id']}/match", json={"journal_line_id": entry["lines"][0]["id"]})
    result = client.put(f"/api/accounting/bank-transactions/{tx['id']}/unmatch").get_json()
    assert result["cleared"] == 0
    assert result["matched_journal_line_id"] is None


def test_delete_bank_transaction(client):
    business, cash, _, _ = _setup(client)
    tx = client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-15", "amount": 500, "type": "fee"}).get_json()
    response = client.delete(f"/api/accounting/bank-transactions/{tx['id']}")
    assert response.status_code == 200
    txs = client.get(f"/api/accounting/bank-transactions?business_id={business['id']}").get_json()
    assert len(txs) == 0


def test_bank_reconciliation_summary(client):
    business, cash, revenue, _ = _setup(client)
    entry = _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    tx = client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-15", "amount": 5000, "type": "deposit"}).get_json()
    client.put(f"/api/accounting/bank-transactions/{tx['id']}/match", json={"journal_line_id": entry["lines"][0]["id"]})
    # Add uncleared transaction
    client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-20", "amount": 1000, "type": "withdrawal"})
    summary = client.get(f"/api/accounting/bank-reconciliation/summary?business_id={business['id']}&account_id={cash['id']}").get_json()
    assert summary["cleared_count"] == 1
    assert summary["uncleared_count"] == 1
    assert summary["cleared_total"] == 5000
    assert summary["uncleared_total"] == -1000


def test_bank_transaction_invalid_type(client):
    business, cash, _, _ = _setup(client)
    response = client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-15", "amount": 100, "type": "invalid"})
    assert response.status_code == 400


def test_bank_transaction_invalid_amount(client):
    business, cash, _, _ = _setup(client)
    response = client.post("/api/accounting/bank-transactions", json={"business_id": business["id"], "account_id": cash["id"], "transaction_date": "2026-01-15", "amount": -100, "type": "deposit"})
    assert response.status_code == 400


def test_bank_transactions_isolated_per_business(client):
    first, cash1, _, _ = _setup(client, "First Bank LLC")
    second, cash2, _, _ = _setup(client, "Second Bank LLC")
    client.post("/api/accounting/bank-transactions", json={"business_id": first["id"], "account_id": cash1["id"], "transaction_date": "2026-01-15", "amount": 500, "type": "deposit"})
    t1 = client.get(f"/api/accounting/bank-transactions?business_id={first['id']}").get_json()
    t2 = client.get(f"/api/accounting/bank-transactions?business_id={second['id']}").get_json()
    assert len(t1) == 1
    assert len(t2) == 0


def test_bank_transactions_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/bank-transactions?business_id=1").status_code == 401
    assert client.post("/api/accounting/bank-transactions", json={}).status_code == 401
