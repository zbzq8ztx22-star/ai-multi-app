from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


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


def test_ar_aging_buckets_open_invoices(client):
    business, cash, receivable, revenue, expense = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    _invoice(client, business["id"], customer["id"], "INV-2", "2026-01-01", "2026-02-15", 500, receivable["id"], revenue["id"])
    report = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert len(report["lines"]) == 2
    assert report["total_outstanding"] == 1500
    inv1 = next(l for l in report["lines"] if l["invoice_number"] == "INV-1")
    inv2 = next(l for l in report["lines"] if l["invoice_number"] == "INV-2")
    assert inv1["bucket"] == "1-30"
    assert inv2["bucket"] == "1-30"


def test_ar_aging_excludes_paid_invoices(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    client.post("/api/accounting/payments", json={"invoice_id": inv["id"], "payment_date": "2026-01-15", "amount": 1000, "cash_account_id": cash["id"]})
    report = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert report["lines"] == []
    assert report["total_outstanding"] == 0


def test_ar_aging_current_bucket(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-FUT", "2026-06-01", "2026-07-31", 2000, receivable["id"], revenue["id"])
    report = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-06-15").get_json()
    assert report["lines"][0]["bucket"] == "current"
    assert report["totals"]["current"] == 2000


def test_ap_aging_tracks_liability_expenses(client):
    business, cash, _, _, expense = _acct_setup(client)
    ap = _account(client, business["id"], "2000", "Accounts Payable", "liability")
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Vendor", "contact_type": "vendor"}).get_json()
    _expense(client, business["id"], ap["id"], expense["id"], "2026-01-01", 800, vendor["id"])
    report = client.get(f"/api/accounting/reports/ap-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert len(report["lines"]) == 1
    assert report["total_outstanding"] == 800
    assert report["lines"][0]["bucket"] == "31-60"


def test_ap_aging_excludes_cash_expenses(client):
    business, cash, _, _, expense = _acct_setup(client)
    _expense(client, business["id"], cash["id"], expense["id"], "2026-01-01", 500)
    report = client.get(f"/api/accounting/reports/ap-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert report["lines"] == []
    assert report["total_outstanding"] == 0


def test_aging_reports_isolated_per_business(client):
    first, cash1, rec1, rev1, _ = _acct_setup(client)
    second = _business(client, "Second LLC")
    customer = client.post("/api/accounting/contacts", json={"business_id": first["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, first["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-31", 1000, rec1["id"], rev1["id"])
    r1 = client.get(f"/api/accounting/reports/ar-aging?business_id={first['id']}&as_of=2026-02-28").get_json()
    r2 = client.get(f"/api/accounting/reports/ar-aging?business_id={second['id']}&as_of=2026-02-28").get_json()
    assert r1["total_outstanding"] == 1000
    assert r2["total_outstanding"] == 0


def test_aging_reports_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/ar-aging?business_id=1").status_code == 401
    assert client.get("/api/accounting/reports/ap-aging?business_id=1").status_code == 401


def test_ar_aging_90_plus_bucket(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-OLD", "2025-10-01", "2025-10-31", 3000, receivable["id"], revenue["id"])
    report = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert report["lines"][0]["bucket"] == "90+"
    assert report["totals"]["90+"] == 3000
