from .test_accounting import _account, _business


def _setup(client, name="1099 LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    ap = _account(client, business["id"], "2000", "AP", "liability")
    expense = _account(client, business["id"], "6000", "Contractors", "expense")
    return business, cash, ap, expense


def _vendor(client, business_id, name):
    return client.post("/api/accounting/contacts", json={"business_id": business_id, "name": name, "contact_type": "vendor"}).get_json()


def _expense(client, business_id, date, amount, vendor_id, ap_id, expense_id):
    return client.post("/api/accounting/expenses", json={
        "business_id": business_id, "expense_date": date, "amount": amount,
        "description": "Contract work", "payment_account_id": ap_id, "expense_account_id": expense_id,
        "vendor_id": vendor_id,
    }).get_json()


def test_update_contact_1099(client):
    business, _, _, _ = _setup(client)
    vendor = _vendor(client, business["id"], "Contractor A")
    result = client.put(f"/api/accounting/contacts/{vendor['id']}/1099", json={"is_1099": True, "tax_id": "123-45-6789"}).get_json()
    assert result["is_1099"] == 1
    assert result["tax_id"] == "123-45-6789"


def test_list_1099_vendors(client):
    business, _, _, _ = _setup(client)
    v1 = _vendor(client, business["id"], "Contractor A")
    v2 = _vendor(client, business["id"], "Contractor B")
    client.put(f"/api/accounting/contacts/{v1['id']}/1099", json={"is_1099": True, "tax_id": "111-11-1111"})
    vendors = client.get(f"/api/accounting/contacts/1099-vendors?business_id={business['id']}").get_json()
    assert len(vendors) == 1
    assert vendors[0]["name"] == "Contractor A"


def test_report_1099_empty(client):
    business, _, _, _ = _setup(client)
    result = client.get(f"/api/accounting/reports/1099?business_id={business['id']}&tax_year=2026").get_json()
    assert result["vendor_count"] == 0
    assert result["total_payments"] == 0


def test_report_1099_with_payments(client):
    business, cash, ap, expense = _setup(client)
    vendor = _vendor(client, business["id"], "Contractor A")
    client.put(f"/api/accounting/contacts/{vendor['id']}/1099", json={"is_1099": True, "tax_id": "123-45-6789"})
    _expense(client, business["id"], "2026-03-15", 5000, vendor["id"], ap["id"], expense["id"])
    _expense(client, business["id"], "2026-06-20", 3000, vendor["id"], ap["id"], expense["id"])
    result = client.get(f"/api/accounting/reports/1099?business_id={business['id']}&tax_year=2026").get_json()
    assert result["vendor_count"] == 1
    assert result["total_payments"] == 8000
    assert result["entries"][0]["vendor_name"] == "Contractor A"
    assert result["entries"][0]["tax_id"] == "123-45-6789"


def test_report_1099_excludes_non_1099(client):
    business, cash, ap, expense = _setup(client)
    vendor = _vendor(client, business["id"], "Non-1099 Vendor")
    _expense(client, business["id"], "2026-03-15", 5000, vendor["id"], ap["id"], expense["id"])
    result = client.get(f"/api/accounting/reports/1099?business_id={business['id']}&tax_year=2026").get_json()
    assert result["vendor_count"] == 0


def test_report_1099_filters_by_year(client):
    business, cash, ap, expense = _setup(client)
    vendor = _vendor(client, business["id"], "Contractor A")
    client.put(f"/api/accounting/contacts/{vendor['id']}/1099", json={"is_1099": True, "tax_id": "123-45-6789"})
    _expense(client, business["id"], "2025-12-15", 5000, vendor["id"], ap["id"], expense["id"])
    _expense(client, business["id"], "2026-03-15", 3000, vendor["id"], ap["id"], expense["id"])
    result = client.get(f"/api/accounting/reports/1099?business_id={business['id']}&tax_year=2026").get_json()
    assert result["total_payments"] == 3000
    result_2025 = client.get(f"/api/accounting/reports/1099?business_id={business['id']}&tax_year=2025").get_json()
    assert result_2025["total_payments"] == 5000


def test_report_1099_multiple_vendors(client):
    business, cash, ap, expense = _setup(client)
    v1 = _vendor(client, business["id"], "Contractor A")
    v2 = _vendor(client, business["id"], "Contractor B")
    client.put(f"/api/accounting/contacts/{v1['id']}/1099", json={"is_1099": True, "tax_id": "111"})
    client.put(f"/api/accounting/contacts/{v2['id']}/1099", json={"is_1099": True, "tax_id": "222"})
    _expense(client, business["id"], "2026-03-15", 5000, v1["id"], ap["id"], expense["id"])
    _expense(client, business["id"], "2026-06-20", 7000, v2["id"], ap["id"], expense["id"])
    result = client.get(f"/api/accounting/reports/1099?business_id={business['id']}&tax_year=2026").get_json()
    assert result["vendor_count"] == 2
    assert result["total_payments"] == 12000


def test_report_1099_isolated_per_business(client):
    first, cash1, ap1, exp1 = _setup(client, "First 1099 LLC")
    second, cash2, ap2, exp2 = _setup(client, "Second 1099 LLC")
    v1 = _vendor(client, first["id"], "Contractor A")
    client.put(f"/api/accounting/contacts/{v1['id']}/1099", json={"is_1099": True, "tax_id": "111"})
    _expense(client, first["id"], "2026-03-15", 5000, v1["id"], ap1["id"], exp1["id"])
    r1 = client.get(f"/api/accounting/reports/1099?business_id={first['id']}&tax_year=2026").get_json()
    r2 = client.get(f"/api/accounting/reports/1099?business_id={second['id']}&tax_year=2026").get_json()
    assert r1["total_payments"] == 5000
    assert r2["total_payments"] == 0


def test_report_1099_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/1099?business_id=1&tax_year=2026").status_code == 401
