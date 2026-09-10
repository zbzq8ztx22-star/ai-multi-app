from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def _invoice(client, business_id, customer_id, number, issue_date, due_date, amount, receivable_id, revenue_id):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "description": "Test invoice", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


def test_get_invoice_detail(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-DET-1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    detail = client.get(f"/api/accounting/invoices/{inv['id']}").get_json()
    assert detail["invoice_number"] == "INV-DET-1"
    assert detail["customer_name"] == "Buyer"
    assert detail["business_name"] == "Operations LLC"
    assert detail["amount"] == 1000


def test_get_invoice_detail_not_found(client):
    response = client.get("/api/accounting/invoices/9999")
    assert response.status_code == 404


def test_void_invoice(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-VOID-1", "2026-01-01", "2026-01-31", 500, receivable["id"], revenue["id"])
    response = client.put(f"/api/accounting/invoices/{inv['id']}/void")
    assert response.status_code == 200
    assert response.get_json()["status"] == "void"
    # Voided invoice should not appear in AR aging
    aging = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert all(l["invoice_number"] != "INV-VOID-1" for l in aging["lines"])


def test_void_paid_invoice_rejected(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-VOID-2", "2026-01-01", "2026-01-31", 500, receivable["id"], revenue["id"])
    client.post("/api/accounting/payments", json={"invoice_id": inv["id"], "payment_date": "2026-01-15", "amount": 500, "cash_account_id": cash["id"]})
    response = client.put(f"/api/accounting/invoices/{inv['id']}/void")
    assert response.status_code == 400


def test_void_invoice_not_found(client):
    response = client.put("/api/accounting/invoices/9999/void")
    assert response.status_code == 400


def test_print_invoice_html(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-PRINT-1", "2026-01-01", "2026-01-31", 1500, receivable["id"], revenue["id"])
    response = client.get(f"/api/accounting/invoices/{inv['id']}/print")
    assert response.status_code == 200
    assert response.mimetype == "text/html"
    text = response.get_data(as_text=True)
    assert "INVOICE" in text
    assert "INV-PRINT-1" in text
    assert "Buyer" in text
    assert "Operations LLC" in text
    assert "1,500.00" in text
    assert "window.print()" in text


def test_print_invoice_not_found(client):
    response = client.get("/api/accounting/invoices/9999/print")
    assert response.status_code == 404


def test_invoice_endpoints_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/invoices/1").status_code == 401
    assert client.put("/api/accounting/invoices/1/void").status_code == 401
    assert client.get("/api/accounting/invoices/1/print").status_code == 401
