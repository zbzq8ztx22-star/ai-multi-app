from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def test_dashboard_summary_empty(client):
    business = _business(client, "Empty Dashboard LLC")
    result = client.get(f"/api/accounting/dashboard-summary?business_id={business['id']}").get_json()
    assert result["cash_balance"] == 0
    assert result["open_invoices"] == 0
    assert result["pending_expenses"] == 0
    assert result["vendors_1099"] == 0
    assert result["active_fixed_assets"] == 0
    assert result["customer_count"] == 0
    assert result["vendor_count"] == 0
    assert result["account_count"] == 0


def test_dashboard_summary_with_data(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    # Create customer
    customer = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Buyer", "contact_type": "customer"}).get_json()
    # Create invoice
    client.post("/api/accounting/invoices", json={
        "business_id": business["id"], "customer_id": customer["id"], "invoice_number": "INV-1",
        "issue_date": "2026-01-01", "due_date": "2026-01-31", "description": "Test", "amount": 5000,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    result = client.get(f"/api/accounting/dashboard-summary?business_id={business['id']}").get_json()
    assert result["open_invoices"] == 1
    assert result["outstanding_receivables"] == 5000
    assert result["customer_count"] == 1
    assert result["account_count"] > 0


def test_dashboard_summary_cash_balance(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    # Add cash via journal entry
    client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-01-01", "description": "Opening",
        "lines": [{"account_id": cash["id"], "debit": 15000}, {"account_id": revenue["id"], "credit": 15000}],
    })
    result = client.get(f"/api/accounting/dashboard-summary?business_id={business['id']}").get_json()
    assert result["cash_balance"] == 15000
    assert result["total_revenue_ytd"] > 0


def test_dashboard_summary_pending_expenses(client):
    business, cash, receivable, revenue, expense = _acct_setup(client)
    client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "expense_date": "2026-01-15", "amount": 500,
        "description": "Pending", "payment_account_id": cash["id"], "expense_account_id": expense["id"],
        "approval_status": "pending",
    })
    result = client.get(f"/api/accounting/dashboard-summary?business_id={business['id']}").get_json()
    assert result["pending_expenses"] == 1
    assert result["pending_expense_total"] == 500


def test_dashboard_summary_1099_vendors(client):
    business = _business(client, "1099 Dashboard LLC")
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Contractor", "contact_type": "vendor"}).get_json()
    client.put(f"/api/accounting/contacts/{vendor['id']}/1099", json={"is_1099": True, "tax_id": "123"})
    result = client.get(f"/api/accounting/dashboard-summary?business_id={business['id']}").get_json()
    assert result["vendors_1099"] == 1
    assert result["vendor_count"] == 1


def test_dashboard_summary_fixed_assets(client):
    business = _business(client, "Assets Dashboard LLC")
    asset = _account(client, business["id"], "1500", "Equipment", "asset")
    accum = _account(client, business["id"], "1510", "Accum Dep", "asset")
    dep = _account(client, business["id"], "6010", "Dep Expense", "expense")
    client.post("/api/accounting/depreciation-assets", json={
        "business_id": business["id"], "name": "Server", "asset_account_id": asset["id"],
        "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"],
        "cost": 10000, "salvage_value": 0, "useful_life_months": 12, "method": "straight_line",
        "acquisition_date": "2026-01-01", "start_date": "2026-01-01",
    })
    result = client.get(f"/api/accounting/dashboard-summary?business_id={business['id']}").get_json()
    assert result["active_fixed_assets"] == 1
    assert result["fixed_asset_total"] == 10000


def test_dashboard_summary_purchase_orders(client):
    business = _business(client, "PO Dashboard LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    expense = _account(client, business["id"], "6000", "Supplies", "expense")
    client.post("/api/accounting/purchase-orders", json={
        "business_id": business["id"], "po_number": "PO-1", "order_date": "2026-01-15",
        "expense_account_id": expense["id"], "payment_account_id": cash["id"],
        "lines": [{"description": "Supplies", "quantity": 10, "unit_price": 5.0}],
    })
    result = client.get(f"/api/accounting/dashboard-summary?business_id={business['id']}").get_json()
    assert result["open_purchase_orders"] == 1
    assert result["open_po_total"] == 50.0


def test_dashboard_summary_isolated_per_business(client):
    first = _business(client, "First Dashboard LLC")
    second = _business(client, "Second Dashboard LLC")
    r1 = client.get(f"/api/accounting/dashboard-summary?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/dashboard-summary?business_id={second['id']}").get_json()
    assert r1["account_count"] == 0
    assert r2["account_count"] == 0
    # Add account to first only
    _account(client, first["id"], "1000", "Cash", "asset")
    r1 = client.get(f"/api/accounting/dashboard-summary?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/dashboard-summary?business_id={second['id']}").get_json()
    assert r1["account_count"] == 1
    assert r2["account_count"] == 0


def test_dashboard_summary_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/dashboard-summary?business_id=1").status_code == 401
