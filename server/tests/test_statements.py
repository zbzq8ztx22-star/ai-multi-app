from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def _invoice(client, business_id, customer_id, number, issue_date, due_date, amount, receivable_id, revenue_id):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "description": "Test", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


def _expense(client, business_id, payment_account_id, expense_account_id, expense_date, amount, vendor_id=None):
    return client.post("/api/accounting/expenses", json={
        "business_id": business_id, "vendor_id": vendor_id, "expense_date": expense_date,
        "reference": "R-EXP", "description": "Test expense", "amount": amount,
        "expense_account_id": expense_account_id, "payment_account_id": payment_account_id,
    }).get_json()


def test_customer_statement_with_invoices(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-S1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    _invoice(client, business["id"], customer["id"], "INV-S2", "2026-02-01", "2026-02-28", 2000, receivable["id"], revenue["id"])
    stmt = client.get(f"/api/accounting/statements/customer/{customer['id']}?business_id={business['id']}").get_json()
    assert stmt["customer"]["name"] == "Buyer"
    assert len(stmt["invoices"]) == 2
    assert stmt["total_invoiced"] == 3000
    assert stmt["total_paid"] == 0
    assert stmt["balance_due"] == 3000


def test_customer_statement_with_payments(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-P1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    client.post("/api/accounting/payments", json={"invoice_id": inv["id"], "payment_date": "2026-01-15", "amount": 600, "cash_account_id": cash["id"]})
    stmt = client.get(f"/api/accounting/statements/customer/{customer['id']}?business_id={business['id']}").get_json()
    assert stmt["total_invoiced"] == 1000
    assert stmt["total_paid"] == 600
    assert stmt["balance_due"] == 400
    assert len(stmt["payments"]) == 1


def test_customer_statement_date_filter(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-JAN", "2026-01-01", "2026-01-31", 500, receivable["id"], revenue["id"])
    _invoice(client, business["id"], customer["id"], "INV-FEB", "2026-02-01", "2026-02-28", 700, receivable["id"], revenue["id"])
    stmt = client.get(f"/api/accounting/statements/customer/{customer['id']}?business_id={business['id']}&start_date=2026-02-01&end_date=2026-02-28").get_json()
    assert len(stmt["invoices"]) == 1
    assert stmt["invoices"][0]["invoice_number"] == "INV-FEB"


def test_customer_statement_not_found(client):
    business, _, _, _, _ = _acct_setup(client)
    response = client.get(f"/api/accounting/statements/customer/9999?business_id={business['id']}")
    assert response.status_code == 400


def test_vendor_statement_with_expenses(client):
    business, cash, _, _, expense = _acct_setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Supplier", "contact_type": "vendor"}).get_json()
    _expense(client, business["id"], cash["id"], expense["id"], "2026-01-10", 500, vendor["id"])
    _expense(client, business["id"], cash["id"], expense["id"], "2026-02-15", 800, vendor["id"])
    stmt = client.get(f"/api/accounting/statements/vendor/{vendor['id']}?business_id={business['id']}").get_json()
    assert stmt["vendor"]["name"] == "Supplier"
    assert len(stmt["expenses"]) == 2
    assert stmt["total_spent"] == 1300
    assert stmt["expense_count"] == 2


def test_vendor_statement_date_filter(client):
    business, cash, _, _, expense = _acct_setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Supplier", "contact_type": "vendor"}).get_json()
    _expense(client, business["id"], cash["id"], expense["id"], "2026-01-10", 500, vendor["id"])
    _expense(client, business["id"], cash["id"], expense["id"], "2026-02-15", 800, vendor["id"])
    stmt = client.get(f"/api/accounting/statements/vendor/{vendor['id']}?business_id={business['id']}&start_date=2026-02-01&end_date=2026-02-28").get_json()
    assert len(stmt["expenses"]) == 1
    assert stmt["total_spent"] == 800


def test_vendor_statement_not_found(client):
    business, _, _, _, _ = _acct_setup(client)
    response = client.get(f"/api/accounting/statements/vendor/9999?business_id={business['id']}")
    assert response.status_code == 400


def test_statements_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/statements/customer/1?business_id=1").status_code == 401
    assert client.get("/api/accounting/statements/vendor/1?business_id=1").status_code == 401
