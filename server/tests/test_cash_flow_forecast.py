from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })


def _invoice(client, business_id, customer_id, number, issue_date, due_date, amount, receivable_id, revenue_id):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "description": "Test", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


def _setup(client, name="Forecast LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    receivable = _account(client, business["id"], "1100", "AR", "asset")
    ap = _account(client, business["id"], "2000", "AP", "liability")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Expense", "expense")
    return business, cash, receivable, ap, revenue, expense


def test_cash_flow_forecast_empty(client):
    business = _business(client, "Empty Forecast LLC")
    result = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}").get_json()
    assert result["current_cash_balance"] == 0
    assert len(result["monthly_forecast"]) == 3
    assert result["total_expected_inflows"] == 0
    assert result["total_expected_outflows"] == 0


def test_cash_flow_forecast_with_receivables(client):
    business, cash, receivable, ap, revenue, expense = _setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    # Create invoice due next month
    import datetime
    next_month = datetime.date.today().replace(day=15)
    if next_month.month == 12:
        next_month = next_month.replace(year=next_month.year + 1, month=1)
    else:
        next_month = next_month.replace(month=next_month.month + 1)
    due_date = next_month.isoformat()
    _invoice(client, business["id"], customer["id"], "INV-1", "2026-01-01", due_date, 5000, receivable["id"], revenue["id"])
    result = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}").get_json()
    assert result["total_expected_inflows"] > 0


def test_cash_flow_forecast_with_payables(client):
    business, cash, receivable, ap, revenue, expense = _setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Vendor", "contact_type": "vendor"}).get_json()
    # Create expense paid with AP (liability) - use a future date within forecast range
    import datetime
    next_month = datetime.date.today().replace(day=15)
    if next_month.month == 12:
        next_month = next_month.replace(year=next_month.year + 1, month=1)
    else:
        next_month = next_month.replace(month=next_month.month + 1)
    client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "expense_date": next_month.isoformat(), "amount": 3000,
        "description": "Supplies", "payment_account_id": ap["id"], "expense_account_id": expense["id"],
        "vendor_id": vendor["id"],
    })
    result = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}").get_json()
    assert result["total_expected_outflows"] > 0


def test_cash_flow_forecast_custom_months(client):
    business = _business(client, "Custom Months LLC")
    result = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}&months=6").get_json()
    assert len(result["monthly_forecast"]) == 6


def test_cash_flow_forecast_invalid_months(client):
    business = _business(client, "Bad Months LLC")
    response = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}&months=0")
    assert response.status_code == 400
    response = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}&months=15")
    assert response.status_code == 400


def test_cash_flow_forecast_with_cash_balance(client):
    business, cash, _, _, revenue, _ = _setup(client)
    # Add cash via journal entry
    _entry(client, business["id"], "2026-01-01", "Opening", [{"account_id": cash["id"], "debit": 10000}, {"account_id": revenue["id"], "credit": 10000}])
    result = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}").get_json()
    assert result["current_cash_balance"] == 10000
    assert result["projected_ending_balance"] == 10000


def test_cash_flow_forecast_isolated_per_business(client):
    first, cash1, _, _, rev1, _ = _setup(client, "First Forecast LLC")
    second, cash2, _, _, rev2, _ = _setup(client, "Second Forecast LLC")
    _entry(client, first["id"], "2026-01-01", "Opening", [{"account_id": cash1["id"], "debit": 10000}, {"account_id": rev1["id"], "credit": 10000}])
    r1 = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={second['id']}").get_json()
    assert r1["current_cash_balance"] == 10000
    assert r2["current_cash_balance"] == 0


def test_cash_flow_forecast_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/cash-flow-forecast?business_id=1").status_code == 401
