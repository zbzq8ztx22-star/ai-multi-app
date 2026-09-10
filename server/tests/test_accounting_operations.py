from .test_accounting import _account, _business


def _setup(client):
    business = _business(client, "Operations LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    receivable = _account(client, business["id"], "1100", "Accounts Receivable", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Office Expense", "expense")
    return business, cash, receivable, revenue, expense


def test_invoice_and_payment_generate_balanced_entries(client):
    business, cash, receivable, revenue, _ = _setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Acme", "contact_type": "customer"}).get_json()
    response = client.post("/api/accounting/invoices", json={
        "business_id": business["id"], "customer_id": customer["id"], "invoice_number": "INV-001",
        "issue_date": "2026-03-01", "due_date": "2026-03-31", "description": "Consulting", "amount": 1200,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    assert response.status_code == 201
    invoice = response.get_json()
    payment = client.post("/api/accounting/payments", json={"invoice_id": invoice["id"], "payment_date": "2026-03-15", "amount": 1200, "cash_account_id": cash["id"]})
    assert payment.status_code == 201
    invoices = client.get(f"/api/accounting/invoices?business_id={business['id']}").get_json()
    assert invoices[0]["status"] == "paid"
    assert invoices[0]["amount_paid"] == 1200
    balance = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert balance["balanced"] is True
    assert balance["total_debits"] == 2400


def test_payment_cannot_exceed_invoice_balance(client):
    business, cash, receivable, revenue, _ = _setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    invoice = client.post("/api/accounting/invoices", json={
        "business_id": business["id"], "customer_id": customer["id"], "invoice_number": "INV-002",
        "issue_date": "2026-03-01", "due_date": "2026-03-31", "description": "Work", "amount": 100,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    }).get_json()
    response = client.post("/api/accounting/payments", json={"invoice_id": invoice["id"], "payment_date": "2026-03-10", "amount": 101, "cash_account_id": cash["id"]})
    assert response.status_code == 400


def test_expense_generates_balanced_entry(client):
    business, cash, _, _, expense_account = _setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Supply Co", "contact_type": "vendor"}).get_json()
    response = client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "vendor_id": vendor["id"], "expense_date": "2026-04-01",
        "reference": "R-100", "description": "Office supplies", "amount": 75.5,
        "expense_account_id": expense_account["id"], "payment_account_id": cash["id"],
    })
    assert response.status_code == 201
    expenses = client.get(f"/api/accounting/expenses?business_id={business['id']}").get_json()
    assert expenses[0]["vendor_name"] == "Supply Co"
    balance = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert balance["total_debits"] == 75.5
    assert balance["total_credits"] == 75.5


def test_customer_vendor_roles_are_enforced(client):
    business, _, receivable, revenue, expense = _setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Vendor", "contact_type": "vendor"}).get_json()
    response = client.post("/api/accounting/invoices", json={
        "business_id": business["id"], "customer_id": vendor["id"], "invoice_number": "BAD",
        "issue_date": "2026-01-01", "due_date": "2026-01-02", "description": "Bad", "amount": 10,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    assert response.status_code == 400
