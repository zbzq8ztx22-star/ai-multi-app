from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def test_export_1099_csv(client):
    business = _business(client, "1099 Export LLC")
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Contractor", "contact_type": "vendor"}).get_json()
    client.put(f"/api/accounting/contacts/{vendor['id']}/1099", json={"is_1099": True, "tax_id": "123"})
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    ap = _account(client, business["id"], "2000", "AP", "liability")
    expense = _account(client, business["id"], "6000", "Expense", "expense")
    client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "expense_date": "2026-03-15", "amount": 5000,
        "description": "Work", "payment_account_id": ap["id"], "expense_account_id": expense["id"],
        "vendor_id": vendor["id"],
    })
    response = client.get(f"/api/accounting/export/1099.csv?business_id={business['id']}&tax_year=2026")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert b"Contractor" in response.data
    assert b"5000" in response.data


def test_export_sales_tax_summary_csv(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    client.post("/api/accounting/sales-tax-rates", json={"business_id": business["id"], "name": "Default", "rate": 10, "is_default": True})
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    client.post("/api/accounting/invoices", json={
        "business_id": business["id"], "customer_id": customer["id"], "invoice_number": "INV-1",
        "issue_date": "2026-01-01", "due_date": "2026-01-31", "description": "Test", "amount": 1000,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    response = client.get(f"/api/accounting/export/sales-tax-summary.csv?business_id={business['id']}")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert b"Total Sales" in response.data
    assert b"Default" in response.data


def test_export_aging_summary_csv(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    response = client.get(f"/api/accounting/export/aging-summary.csv?business_id={business['id']}")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert b"Aging Summary" in response.data
    assert b"Net Cash Position" in response.data


def test_export_financial_ratios_csv(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    response = client.get(f"/api/accounting/export/financial-ratios.csv?business_id={business['id']}")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert b"Financial Ratios" in response.data
    assert b"Current Ratio" in response.data


def test_export_fixed_asset_register_csv(client):
    business = _business(client, "FAR Export LLC")
    asset = _account(client, business["id"], "1500", "Equipment", "asset")
    accum = _account(client, business["id"], "1510", "Accum Dep", "asset")
    dep = _account(client, business["id"], "6010", "Dep Expense", "expense")
    client.post("/api/accounting/depreciation-assets", json={
        "business_id": business["id"], "name": "Server", "asset_account_id": asset["id"],
        "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"],
        "cost": 10000, "salvage_value": 0, "useful_life_months": 12, "method": "straight_line",
        "acquisition_date": "2026-01-01", "start_date": "2026-01-01",
    })
    response = client.get(f"/api/accounting/export/fixed-asset-register.csv?business_id={business['id']}")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert b"Server" in response.data
    assert b"10000" in response.data


def test_export_cash_flow_forecast_csv(client):
    business = _business(client, "Forecast Export LLC")
    response = client.get(f"/api/accounting/export/cash-flow-forecast.csv?business_id={business['id']}")
    assert response.status_code == 200
    assert "text/csv" in response.content_type
    assert b"Month" in response.data
    assert b"Projected Ending Balance" in response.data


def test_csv_exports_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/export/1099.csv?business_id=1&tax_year=2026").status_code == 401
    assert client.get("/api/accounting/export/sales-tax-summary.csv?business_id=1").status_code == 401
    assert client.get("/api/accounting/export/aging-summary.csv?business_id=1").status_code == 401
    assert client.get("/api/accounting/export/financial-ratios.csv?business_id=1").status_code == 401
    assert client.get("/api/accounting/export/fixed-asset-register.csv?business_id=1").status_code == 401
    assert client.get("/api/accounting/export/cash-flow-forecast.csv?business_id=1").status_code == 401
