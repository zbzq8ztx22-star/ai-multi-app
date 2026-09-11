from .test_accounting import _account, _business


def _setup(client, name="Aging LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    receivable = _account(client, business["id"], "1100", "AR", "asset")
    ap = _account(client, business["id"], "2000", "AP", "liability")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Expense", "expense")
    return business, cash, receivable, ap, revenue, expense


def _invoice(client, business_id, customer_id, number, issue_date, due_date, amount, receivable_id, revenue_id):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "description": "Test", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


def test_aging_summary_empty(client):
    business, _, _, _, _, _ = _setup(client)
    result = client.get(f"/api/accounting/reports/aging-summary?business_id={business['id']}").get_json()
    assert result["ar_total"] == 0
    assert result["ap_total"] == 0
    assert result["net_cash_position"] == 0
    assert len(result["buckets"]) == 5


def test_aging_summary_with_receivables(client):
    business, cash, receivable, ap, revenue, expense = _setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    # Create overdue invoice
    _invoice(client, business["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-15", 5000, receivable["id"], revenue["id"])
    result = client.get(f"/api/accounting/reports/aging-summary?business_id={business['id']}&as_of=2026-03-01").get_json()
    assert result["ar_total"] == 5000
    assert result["ap_total"] == 0
    assert result["net_cash_position"] == 5000
    # 2026-03-01 - 2026-01-15 = 45 days overdue -> bucket 31-60
    assert result["ar_totals"]["31-60"] == 5000


def test_aging_summary_with_payables(client):
    business, cash, receivable, ap, revenue, expense = _setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Vendor", "contact_type": "vendor"}).get_json()
    # Create expense paid with AP (liability account)
    client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "expense_date": "2026-01-01", "amount": 3000,
        "description": "Office supplies", "payment_account_id": ap["id"], "expense_account_id": expense["id"],
        "vendor_id": vendor["id"],
    })
    result = client.get(f"/api/accounting/reports/aging-summary?business_id={business['id']}&as_of=2026-03-01").get_json()
    assert result["ar_total"] == 0
    assert result["ap_total"] == 3000
    assert result["net_cash_position"] == -3000


def test_aging_summary_with_both(client):
    business, cash, receivable, ap, revenue, expense = _setup(client)
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Vendor", "contact_type": "vendor"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-15", 8000, receivable["id"], revenue["id"])
    client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "expense_date": "2026-01-01", "amount": 3000,
        "description": "Supplies", "payment_account_id": ap["id"], "expense_account_id": expense["id"],
        "vendor_id": vendor["id"],
    })
    result = client.get(f"/api/accounting/reports/aging-summary?business_id={business['id']}&as_of=2026-03-01").get_json()
    assert result["ar_total"] == 8000
    assert result["ap_total"] == 3000
    assert result["net_cash_position"] == 5000
    assert result["ar_invoice_count"] == 1
    assert result["ap_expense_count"] == 1


def test_aging_summary_buckets_structure(client):
    business, _, _, _, _, _ = _setup(client)
    result = client.get(f"/api/accounting/reports/aging-summary?business_id={business['id']}").get_json()
    buckets = result["buckets"]
    assert len(buckets) == 5
    bucket_names = [b["bucket"] for b in buckets]
    assert bucket_names == ["current", "1-30", "31-60", "61-90", "90+"]
    for b in buckets:
        assert "receivable" in b
        assert "payable" in b
        assert "net" in b


def test_aging_summary_isolated_per_business(client):
    first, cash1, rec1, ap1, rev1, exp1 = _setup(client, "First Aging LLC")
    second, cash2, rec2, ap2, rev2, exp2 = _setup(client, "Second Aging LLC")
    customer = client.post("/api/accounting/contacts", json={"business_id": first["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, first["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-15", 5000, rec1["id"], rev1["id"])
    r1 = client.get(f"/api/accounting/reports/aging-summary?business_id={first['id']}&as_of=2026-03-01").get_json()
    r2 = client.get(f"/api/accounting/reports/aging-summary?business_id={second['id']}&as_of=2026-03-01").get_json()
    assert r1["ar_total"] == 5000
    assert r2["ar_total"] == 0


def test_aging_summary_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/aging-summary?business_id=1").status_code == 401
