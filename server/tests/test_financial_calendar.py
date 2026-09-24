from .test_accounting import _business
from .test_accounting_operations import _setup as _acct_setup


def _entry(client, business_id, entry_date, description, lines):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def _invoice(client, business_id, customer_id, number, issue_date, due_date, amount, receivable_id, revenue_id):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "description": "Test", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


def test_calendar_includes_open_invoices(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-CAL-1", "2026-01-01", "2026-02-15", 1000, receivable["id"], revenue["id"])
    cal = client.get(f"/api/dashboard/calendar?business_id={business['id']}&start_date=2026-01-01&end_date=2026-03-31").get_json()
    inv_events = [e for e in cal["events"] if e["type"] == "invoice_due"]
    assert len(inv_events) == 1
    assert inv_events[0]["date"] == "2026-02-15"
    assert inv_events[0]["amount"] == 1000


def test_calendar_excludes_paid_invoices(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-CAL-2", "2026-01-01", "2026-02-15", 500, receivable["id"], revenue["id"])
    client.post("/api/accounting/payments", json={"invoice_id": inv["id"], "payment_date": "2026-01-10", "amount": 500, "cash_account_id": cash["id"]})
    cal = client.get(f"/api/dashboard/calendar?business_id={business['id']}&start_date=2026-01-01&end_date=2026-03-31").get_json()
    inv_events = [e for e in cal["events"] if e["type"] == "invoice_due"]
    assert len(inv_events) == 0


def test_calendar_includes_recurring_expenses(client):
    business, cash, _, _, expense = _acct_setup(client)
    client.post("/api/accounting/recurring-expenses", json={"business_id": business["id"], "description": "Monthly rent", "amount": 2000, "expense_account_id": expense["id"], "payment_account_id": cash["id"], "frequency": "monthly", "start_date": "2026-02-01"})
    cal = client.get(f"/api/dashboard/calendar?business_id={business['id']}&start_date=2026-01-01&end_date=2026-03-31").get_json()
    rec_events = [e for e in cal["events"] if e["type"] == "recurring_expense"]
    assert len(rec_events) == 1
    assert rec_events[0]["amount"] == 2000


def test_calendar_includes_open_reconciliations(client):
    business, cash, _, _, _ = _acct_setup(client)
    # Create a reconciliation with a discrepancy (statement_balance != book balance)
    client.post("/api/accounting/reconciliations", json={"business_id": business["id"], "account_id": cash["id"], "statement_date": "2026-02-28", "statement_balance": 999})
    cal = client.get(f"/api/dashboard/calendar?business_id={business['id']}&start_date=2026-01-01&end_date=2026-03-31").get_json()
    recon_events = [e for e in cal["events"] if e["type"] == "reconciliation"]
    assert len(recon_events) == 1
    assert recon_events[0]["date"] == "2026-02-28"


def test_calendar_empty_business(client):
    business = _business(client, "Empty Cal LLC")
    cal = client.get(f"/api/dashboard/calendar?business_id={business['id']}&start_date=2026-01-01&end_date=2026-03-31").get_json()
    assert cal["events"] == []
    assert cal["total"] == 0


def test_calendar_isolated_per_business(client):
    first, cash1, rec1, rev1, _ = _acct_setup(client)
    second = _business(client, "Second LLC")
    customer = client.post("/api/accounting/contacts", json={"business_id": first["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, first["id"], customer["id"], "INV-ISO", "2026-01-01", "2026-02-15", 1000, rec1["id"], rev1["id"])
    c1 = client.get(f"/api/dashboard/calendar?business_id={first['id']}&start_date=2026-01-01&end_date=2026-03-31").get_json()
    c2 = client.get(f"/api/dashboard/calendar?business_id={second['id']}&start_date=2026-01-01&end_date=2026-03-31").get_json()
    assert c1["total"] >= 1
    assert c2["total"] == 0


def test_calendar_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/dashboard/calendar?business_id=1&start_date=2026-01-01&end_date=2026-03-31").status_code == 401
