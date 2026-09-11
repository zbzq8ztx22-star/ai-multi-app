from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def _invoice(client, business_id, customer_id, number, issue_date, due_date, amount, receivable_id, revenue_id):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": due_date, "description": "Test", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


def test_create_sales_tax_rate(client):
    business = _business(client, "Sales Tax LLC")
    rate = client.post("/api/accounting/sales-tax-rates", json={
        "business_id": business["id"], "name": "State Sales Tax", "rate": 7.5,
    }).get_json()
    assert rate["name"] == "State Sales Tax"
    assert rate["rate"] == 7.5
    assert rate["active"] == 1


def test_list_sales_tax_rates(client):
    business = _business(client, "List Tax LLC")
    client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "State", "rate": 7.5})
    client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "County", "rate": 2.0})
    rates = client.get(f"/api/accounting/sales-tax-rates?business_id={business['id']}").get_json()
    assert len(rates) == 2


def test_create_duplicate_tax_rate_rejected(client):
    business = _business(client, "Dup Tax LLC")
    client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "State", "rate": 7.5})
    response = client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "State", "rate": 5.0})
    assert response.status_code == 400


def test_create_default_tax_rate(client):
    business = _business(client, "Default Tax LLC")
    rate = client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "Default", "rate": 7.5, "is_default": True}).get_json()
    assert rate["is_default"] == 1


def test_only_one_default_tax_rate(client):
    business = _business(client, "One Default Tax LLC")
    client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "Default", "rate": 7.5, "is_default": True})
    response = client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "Other", "rate": 5.0, "is_default": True})
    assert response.status_code == 400


def test_update_sales_tax_rate(client):
    business = _business(client, "Update Tax LLC")
    rate = client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "State", "rate": 7.5}).get_json()
    response = client.put(f"/api/accounting/sales-tax-rates/{rate['id']}", json={"rate": 8.0, "name": "Updated"})
    assert response.status_code == 200
    assert response.get_json()["rate"] == 8.0
    assert response.get_json()["name"] == "Updated"


def test_delete_sales_tax_rate(client):
    business = _business(client, "Delete Tax LLC")
    rate = client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "State", "rate": 7.5}).get_json()
    response = client.delete(f"/api/accounting/sales-tax-rates/{rate['id']}")
    assert response.status_code == 200
    rates = client.get(f"/api/accounting/sales-tax-rates?business_id={business['id']}").get_json()
    assert len(rates) == 0


def test_calculate_sales_tax(client):
    result = client.get("/api/accounting/sales-tax/calculate?amount=100&rate=7.5").get_json()
    assert result["tax_amount"] == 7.5
    assert result["total"] == 107.5


def test_calculate_sales_tax_invalid_rate(client):
    response = client.get("/api/accounting/sales-tax/calculate?amount=100&rate=150")
    assert response.status_code == 400


def test_sales_tax_summary(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "Default", "rate": 10, "is_default": True})
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    _invoice(client, business["id"], customer["id"], "INV-2", "2026-02-01", "2026-02-28", 2000, receivable["id"], revenue["id"])
    summary = client.get(f"/api/accounting/sales-tax/summary?business_id={business['id']}").get_json()
    assert summary["total_sales"] == 3000
    assert summary["default_rate"] == 10
    assert summary["total_tax_collected"] == 300.0
    assert summary["invoice_count"] == 2


def test_sales_tax_summary_with_date_filter(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "Default", "rate": 10, "is_default": True})
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    _invoice(client, business["id"], customer["id"], "INV-1", "2026-01-01", "2026-01-31", 1000, receivable["id"], revenue["id"])
    _invoice(client, business["id"], customer["id"], "INV-2", "2026-02-01", "2026-02-28", 2000, receivable["id"], revenue["id"])
    summary = client.get(f"/api/accounting/sales-tax/summary?business_id={business['id']}&start_date=2026-02-01&end_date=2026-02-28").get_json()
    assert summary["total_sales"] == 2000
    assert summary["invoice_count"] == 1


def test_sales_tax_invalid_rate_value(client):
    business = _business(client, "Bad Rate Tax LLC")
    response = client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "Bad", "rate": 150})
    assert response.status_code == 400


def test_sales_tax_isolated_per_business(client):
    first = _business(client, "First Tax LLC")
    second = _business(client, "Second Tax LLC")
    client.post("/api/accounting/sales-tax-rates", json={"business_id": first["id"], "name": "State", "rate": 7.5})
    r1 = client.get(f"/api/accounting/sales-tax-rates?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/sales-tax-rates?business_id={second['id']}").get_json()
    assert len(r1) == 1
    assert len(r2) == 0


def test_sales_tax_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/sales-tax-rates?business_id=1").status_code == 401
    assert client.post("/api/accounting/sales-tax-rates", json={}).status_code == 401
