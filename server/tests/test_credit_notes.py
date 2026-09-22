from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def _invoice(client, business_id, customer_id, number, issue_date, due_date, amount, receivable_id, revenue_id):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "description": "Test", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


def test_create_credit_note(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    cn = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-1",
        "credit_date": "2026-01-15", "amount": 500, "reason": "Returned goods",
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    }).get_json()
    assert cn["credit_number"] == "CN-1"
    assert cn["amount"] == 500
    assert cn["status"] == "applied"


def test_list_credit_notes(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-1", "credit_date": "2026-01-15", "amount": 500, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]})
    client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-2", "credit_date": "2026-02-15", "amount": 300, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]})
    cns = client.get(f"/api/accounting/credit-notes?business_id={business['id']}").get_json()
    assert len(cns) == 2


def test_credit_note_linked_to_invoice(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-CN-1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    cn = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-LINK",
        "credit_date": "2026-01-15", "amount": 200, "reason": "Partial refund",
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    }).get_json()
    assert cn["invoice_id"] == inv["id"]
    assert cn["customer_id"] == customer["id"]  # auto-filled from invoice
    # Invoice amount_paid should be increased
    inv_detail = client.get(f"/api/accounting/invoices/{inv['id']}?business_id={business['id']}").get_json()
    assert inv_detail["amount_paid"] == 200


def test_credit_note_creates_balanced_entry(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-BAL", "credit_date": "2026-01-15", "amount": 500, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]})
    # Check trial balance is still balanced
    tb = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert tb["balanced"] is True


def test_void_credit_note(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    cn = client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-VOID", "credit_date": "2026-01-15", "amount": 500, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]}).get_json()
    response = client.put(f"/api/accounting/credit-notes/{cn['id']}/void?business_id={business['id']}")
    assert response.status_code == 200
    assert response.get_json()["status"] == "void"


def test_void_credit_note_already_void(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    cn = client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-VOID2", "credit_date": "2026-01-15", "amount": 500, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]}).get_json()
    client.put(f"/api/accounting/credit-notes/{cn['id']}/void?business_id={business['id']}")
    response = client.put(f"/api/accounting/credit-notes/{cn['id']}/void?business_id={business['id']}")
    assert response.status_code == 400


def test_credit_note_duplicate_number_rejected(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-DUP", "credit_date": "2026-01-15", "amount": 500, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]})
    response = client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-DUP", "credit_date": "2026-02-15", "amount": 300, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]})
    assert response.status_code == 400


def test_credit_note_invalid_amount(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    response = client.post("/api/accounting/credit-notes", json={"business_id": business["id"], "credit_number": "CN-BAD", "credit_date": "2026-01-15", "amount": -100, "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"]})
    assert response.status_code == 400


def test_credit_note_cannot_exceed_invoice_balance(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-OB", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    response = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-OVER",
        "credit_date": "2026-01-15", "amount": 1500,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    assert response.status_code == 400
    assert "balance" in response.get_json()["error"].lower()
    # Partial credits accumulate: two 600 credits against a 1000 invoice — the second must fail
    client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-P1",
        "credit_date": "2026-01-15", "amount": 600,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    response = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-P2",
        "credit_date": "2026-01-16", "amount": 600,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    assert response.status_code == 400
    inv_detail = client.get(f"/api/accounting/invoices/{inv['id']}").get_json()
    assert inv_detail["amount_paid"] == 600


def test_credit_note_full_balance_marks_invoice_paid(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-FULL", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    response = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-FULL",
        "credit_date": "2026-01-15", "amount": 1000,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    assert response.status_code == 201
    inv_detail = client.get(f"/api/accounting/invoices/{inv['id']}").get_json()
    assert inv_detail["amount_paid"] == 1000
    assert inv_detail["status"] == "paid"


def test_credit_note_customer_must_match_invoice(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer_a = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer A", "contact_type": "customer"}).get_json()
    customer_b = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer B", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer_a["id"], "INV-CUST", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    response = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "customer_id": customer_b["id"],
        "credit_number": "CN-MISMATCH", "credit_date": "2026-01-15", "amount": 200,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    assert response.status_code == 400
    assert "customer" in response.get_json()["error"].lower()
    cns = client.get(f"/api/accounting/credit-notes?business_id={business['id']}").get_json()
    assert len(cns) == 0


def test_void_credit_note_restores_invoice_balance_and_status(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-VR", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    cn = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-VR",
        "credit_date": "2026-01-15", "amount": 1000,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    }).get_json()
    assert client.get(f"/api/accounting/invoices/{inv['id']}").get_json()["status"] == "paid"
    response = client.put(f"/api/accounting/credit-notes/{cn['id']}/void?business_id={business['id']}")
    assert response.status_code == 200
    inv_detail = client.get(f"/api/accounting/invoices/{inv['id']}").get_json()
    assert inv_detail["amount_paid"] == 0
    assert inv_detail["status"] == "open"
    tb = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert tb["balanced"] is True


def test_credit_notes_isolated_per_business(client):
    first, cash1, rec1, rev1, _ = _acct_setup(client)
    second = _business(client, "Second CN LLC")
    cash2 = _account(client, second["id"], "1000", "Cash", "asset")
    rec2 = _account(client, second["id"], "1100", "AR", "asset")
    rev2 = _account(client, second["id"], "4000", "Revenue", "revenue")
    cust1 = client.post("/api/accounting/contacts", json={"business_id": first["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    client.post("/api/accounting/credit-notes", json={"business_id": first["id"], "customer_id": cust1["id"], "credit_number": "CN-1", "credit_date": "2026-01-15", "amount": 500, "receivable_account_id": rec1["id"], "revenue_account_id": rev1["id"]})
    c1 = client.get(f"/api/accounting/credit-notes?business_id={first['id']}").get_json()
    c2 = client.get(f"/api/accounting/credit-notes?business_id={second['id']}").get_json()
    assert len(c1) == 1
    assert len(c2) == 0


def test_credit_notes_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/credit-notes?business_id=1").status_code == 401
    assert client.post("/api/accounting/credit-notes", json={}).status_code == 401
