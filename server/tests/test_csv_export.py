from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _setup(client, name="Export LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Office Expense", "expense")
    equity = _account(client, business["id"], "3000", "Owner Equity", "equity")
    return business, cash, revenue, expense, equity


def test_export_profit_loss_csv(client):
    business, cash, revenue, expense, _ = _setup(client)
    _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    _entry(client, business["id"], "2026-01-20", "Cost", [{"account_id": expense["id"], "debit": 2000}, {"account_id": cash["id"], "credit": 2000}])
    response = client.get(f"/api/accounting/export/profit-loss.csv?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers.get("Content-Disposition", "")
    text = response.get_data(as_text=True)
    assert "Revenue" in text
    assert "Net Income" in text
    assert "5000" in text
    assert "3000" in text


def test_export_balance_sheet_csv(client):
    business, cash, _, _, equity = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 10000}, {"account_id": equity["id"], "credit": 10000}])
    response = client.get(f"/api/accounting/export/balance-sheet.csv?business_id={business['id']}&as_of=2026-12-31")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    text = response.get_data(as_text=True)
    assert "Asset" in text
    assert "Equity" in text
    assert "10000" in text
    assert "Yes" in text


def test_export_trial_balance_csv(client):
    business, cash, revenue, _, equity = _setup(client)
    _entry(client, business["id"], "2026-01-01", "Capital", [{"account_id": cash["id"], "debit": 5000}, {"account_id": equity["id"], "credit": 5000}])
    response = client.get(f"/api/accounting/export/trial-balance.csv?business_id={business['id']}")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    text = response.get_data(as_text=True)
    assert "Account Code" in text
    assert "1000" in text
    assert "Totals" in text


def test_export_general_ledger_csv(client):
    business, cash, revenue, _, _ = _setup(client)
    _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 3000}, {"account_id": revenue["id"], "credit": 3000}])
    response = client.get(f"/api/accounting/export/general-ledger.csv?business_id={business['id']}")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    text = response.get_data(as_text=True)
    assert "Date" in text
    assert "3000" in text
    assert "Sale" in text


def test_export_general_ledger_filtered_by_account(client):
    business, cash, revenue, _, _ = _setup(client)
    _entry(client, business["id"], "2026-01-15", "Sale", [{"account_id": cash["id"], "debit": 3000}, {"account_id": revenue["id"], "credit": 3000}])
    response = client.get(f"/api/accounting/export/general-ledger.csv?business_id={business['id']}&account_id={cash['id']}")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    lines = [l for l in text.split("\n") if l.strip() and not l.startswith("Date")]
    assert len(lines) == 1


def test_export_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/export/profit-loss.csv?business_id=1").status_code == 401
    assert client.get("/api/accounting/export/balance-sheet.csv?business_id=1").status_code == 401
    assert client.get("/api/accounting/export/trial-balance.csv?business_id=1").status_code == 401
    assert client.get("/api/accounting/export/general-ledger.csv?business_id=1").status_code == 401


def test_export_invalid_business(client):
    response = client.get("/api/accounting/export/profit-loss.csv?business_id=9999&start_date=2026-01-01&end_date=2026-12-31")
    assert response.status_code == 400


def test_export_empty_business(client):
    business = _business(client, "Empty Export LLC")
    response = client.get(f"/api/accounting/export/profit-loss.csv?business_id={business['id']}&start_date=2026-01-01&end_date=2026-12-31")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert "Net Income" in text
    assert "0" in text
