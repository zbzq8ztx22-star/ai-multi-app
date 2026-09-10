from .test_accounting import _business


def test_create_tax_payment(client):
    business = _business(client, "Tax Pay LLC")
    payment = client.post("/api/tax/payments", json={
        "business_id": business["id"], "tax_type": "federal_estimated",
        "payment_date": "2026-03-15", "amount": 5000,
        "period_start": "2026-01-01", "period_end": "2026-03-31",
        "reference": "Q1-EST", "notes": "Q1 estimated federal",
    }).get_json()
    assert payment["tax_type"] == "federal_estimated"
    assert payment["amount"] == 5000


def test_list_tax_payments(client):
    business = _business(client, "List Tax LLC")
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": 5000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "state_estimated", "payment_date": "2026-03-15", "amount": 1000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    payments = client.get(f"/api/tax/payments?business_id={business['id']}").get_json()
    assert len(payments) == 2


def test_list_tax_payments_filter_by_type(client):
    business = _business(client, "Filter Tax LLC")
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": 5000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "state_estimated", "payment_date": "2026-03-15", "amount": 1000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    payments = client.get(f"/api/tax/payments?business_id={business['id']}&tax_type=federal_estimated").get_json()
    assert len(payments) == 1
    assert payments[0]["tax_type"] == "federal_estimated"


def test_create_tax_payment_invalid_type(client):
    business = _business(client, "Bad Type LLC")
    response = client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "invalid", "payment_date": "2026-03-15", "amount": 100, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    assert response.status_code == 400


def test_create_tax_payment_invalid_amount(client):
    business = _business(client, "Bad Amount LLC")
    response = client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": -100, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    assert response.status_code == 400


def test_create_tax_payment_invalid_dates(client):
    business = _business(client, "Bad Dates LLC")
    response = client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": 100, "period_start": "2026-03-31", "period_end": "2026-01-01"})
    assert response.status_code == 400


def test_delete_tax_payment(client):
    business = _business(client, "Delete Tax LLC")
    payment = client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": 500, "period_start": "2026-01-01", "period_end": "2026-03-31"}).get_json()
    response = client.delete(f"/api/tax/payments/{payment['id']}")
    assert response.status_code == 200
    payments = client.get(f"/api/tax/payments?business_id={business['id']}").get_json()
    assert len(payments) == 0


def test_tax_payment_summary(client):
    business = _business(client, "Summary Tax LLC")
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": 5000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "state_estimated", "payment_date": "2026-03-15", "amount": 1000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-06-15", "amount": 3000, "period_start": "2026-04-01", "period_end": "2026-06-30"})
    summary = client.get(f"/api/tax/payments/summary?business_id={business['id']}&year=2026").get_json()
    assert summary["by_type"]["federal_estimated"]["total"] == 8000
    assert summary["by_type"]["state_estimated"]["total"] == 1000
    assert summary["total_paid"] == 9000


def test_tax_payment_summary_all_years(client):
    business = _business(client, "All Year Tax LLC")
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2025-03-15", "amount": 2000, "period_start": "2025-01-01", "period_end": "2025-03-31"})
    client.post("/api/tax/payments", json={"business_id": business["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": 3000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    summary = client.get(f"/api/tax/payments/summary?business_id={business['id']}").get_json()
    assert summary["total_paid"] == 5000


def test_tax_payments_isolated_per_business(client):
    first = _business(client, "First Tax LLC")
    second = _business(client, "Second Tax LLC")
    client.post("/api/tax/payments", json={"business_id": first["id"], "tax_type": "federal_estimated", "payment_date": "2026-03-15", "amount": 1000, "period_start": "2026-01-01", "period_end": "2026-03-31"})
    p1 = client.get(f"/api/tax/payments?business_id={first['id']}").get_json()
    p2 = client.get(f"/api/tax/payments?business_id={second['id']}").get_json()
    assert len(p1) == 1
    assert len(p2) == 0


def test_tax_payments_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/tax/payments?business_id=1").status_code == 401
    assert client.post("/api/tax/payments", json={}).status_code == 401
