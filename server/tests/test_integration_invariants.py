"""Cross-module integration and accounting-invariant tests."""
import datetime

from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def _tb(client, business_id):
    return client.get(f"/api/accounting/trial-balance?business_id={business_id}").get_json()


def _invoice(client, business_id, customer_id, number, issue, due, amount, receivable_id, revenue_id):
    response = client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue, "due_date": due, "description": "Test", "amount": amount,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    })
    assert response.status_code == 201
    return response.get_json()


def _customer(client, business_id, name="Buyer"):
    return client.post("/api/accounting/contacts", json={"business_id": business_id, "name": name, "contact_type": "customer"}).get_json()


def test_recurring_posting_flows_into_forecast(client):
    business, cash, receivable, revenue, expense = _acct_setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Landlord", "contact_type": "vendor"}).get_json()
    month_0 = datetime.date.today().replace(day=1)
    rec = client.post("/api/accounting/recurring-expenses", json={
        "business_id": business["id"], "vendor_id": vendor["id"], "description": "Rent",
        "amount": 1000, "expense_account_id": expense["id"], "payment_account_id": cash["id"],
        "frequency": "monthly", "start_date": month_0.isoformat(),
    })
    assert rec.status_code == 201
    posted = client.post(f"/api/accounting/recurring-expenses/post-due?business_id={business['id']}&as_of={datetime.date.today().isoformat()}").get_json()
    assert posted["posted_count"] == 1
    expenses = client.get(f"/api/accounting/expenses?business_id={business['id']}").get_json()
    assert len(expenses) == 1 and expenses[0]["amount"] == 1000
    # The posted expense exists as a journal entry and the next occurrence is
    # projected by the forecast — no double counting.
    forecast = client.get(f"/api/accounting/reports/cash-flow-forecast?business_id={business['id']}&months=4").get_json()
    assert forecast["total_expected_outflows"] == 3000  # Feb, Mar, Apr 2026
    assert _tb(client, business["id"])["balanced"] is True


def test_closed_period_blocks_all_posting_paths(client):
    business, cash, receivable, revenue, expense = _acct_setup(client)
    customer = _customer(client, business["id"])
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Vendor", "contact_type": "vendor"}).get_json()
    inv = _invoice(client, business["id"], customer["id"], "INV-CP", "2026-01-10", "2026-02-10", 500, receivable["id"], revenue["id"])
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-01-31"})
    before = _tb(client, business["id"])
    assert client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-01-20", "description": "Late",
        "lines": [{"account_id": cash["id"], "debit": 10}, {"account_id": revenue["id"], "credit": 10}],
    }).status_code == 400
    assert client.post("/api/accounting/invoices", json={
        "business_id": business["id"], "customer_id": customer["id"], "invoice_number": "INV-CP2",
        "issue_date": "2026-01-20", "due_date": "2026-02-20", "amount": 100,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    }).status_code == 400
    assert client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "vendor_id": vendor["id"], "expense_date": "2026-01-20",
        "description": "Late expense", "amount": 50,
        "expense_account_id": expense["id"], "payment_account_id": cash["id"],
    }).status_code == 400
    assert client.post("/api/accounting/payments", json={
        "invoice_id": inv["id"], "payment_date": "2026-01-20", "amount": 500, "cash_account_id": cash["id"],
    }).status_code == 400
    # The ledger is untouched: the closed period is immutable.
    assert _tb(client, business["id"]) == before


def test_credit_note_updates_ar_aging(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = _customer(client, business["id"])
    inv = _invoice(client, business["id"], customer["id"], "INV-AGE", "2026-01-01", "2026-01-15", 1000, receivable["id"], revenue["id"])
    aging = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert aging["total_outstanding"] == 1000
    client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-AGE",
        "credit_date": "2026-02-01", "amount": 400,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    aging = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert aging["total_outstanding"] == 600
    assert _tb(client, business["id"])["balanced"] is True
    # A second credit covering the remainder clears the invoice from aging.
    client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-AGE2",
        "credit_date": "2026-02-05", "amount": 600,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    aging = client.get(f"/api/accounting/reports/ar-aging?business_id={business['id']}&as_of=2026-02-28").get_json()
    assert aging["lines"] == []
    detail = client.get(f"/api/accounting/invoices/{inv['id']}?business_id={business['id']}").get_json()
    assert detail["status"] == "paid" and detail["amount_paid"] == 1000


def test_depreciation_flows_into_balance_sheet(client):
    business, cash, receivable, revenue, expense = _acct_setup(client)
    accum = _account(client, business["id"], "1510", "Accum Dep", "asset")
    equip = _account(client, business["id"], "1500", "Equipment", "asset")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-01-01", "description": "Capital",
        "lines": [{"account_id": cash["id"], "debit": 20000}, {"account_id": equity["id"], "credit": 20000}],
    })
    asset = client.post("/api/accounting/depreciation-assets", json={
        "business_id": business["id"], "name": "Truck", "asset_account_id": equip["id"],
        "accumulated_account_id": accum["id"], "depreciation_account_id": expense["id"],
        "cost": 12000, "salvage_value": 0, "useful_life_months": 12,
        "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01",
    }).get_json()
    # Capitalize the equipment on the books.
    client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-01-01", "description": "Buy truck",
        "lines": [{"account_id": equip["id"], "debit": 12000}, {"account_id": cash["id"], "credit": 12000}],
    })
    client.post(f"/api/accounting/depreciation-assets/{asset['id']}/post", json={"through_date": "2026-03-31"})
    bs = client.get(f"/api/accounting/reports/balance-sheet?business_id={business['id']}&as_of=2026-03-31").get_json()
    # cash 8000 + equipment 12000 - 3000 accumulated depreciation = 17000
    assert bs["total_assets"] == 17000
    assert _tb(client, business["id"])["balanced"] is True


def test_invoice_balance_invariants(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = _customer(client, business["id"])
    inv = _invoice(client, business["id"], customer["id"], "INV-INV", "2026-01-01", "2026-01-31", 800, receivable["id"], revenue["id"])
    # Overpayment and over-credit are both rejected.
    assert client.post("/api/accounting/payments", json={"invoice_id": inv["id"], "payment_date": "2026-01-10", "amount": 801, "cash_account_id": cash["id"]}).status_code == 400
    assert client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-INV",
        "credit_date": "2026-01-10", "amount": 900,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    }).status_code == 400
    # Partial payment + partial credit stays consistent.
    client.post("/api/accounting/payments", json={"invoice_id": inv["id"], "payment_date": "2026-01-10", "amount": 300, "cash_account_id": cash["id"]})
    client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "invoice_id": inv["id"], "credit_number": "CN-INV2",
        "credit_date": "2026-01-11", "amount": 500,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    detail = client.get(f"/api/accounting/invoices/{inv['id']}?business_id={business['id']}").get_json()
    assert detail["amount_paid"] == 800 and detail["status"] == "paid"
    assert _tb(client, business["id"])["balanced"] is True


def test_tenant_isolation_across_modules(client, app):
    a = _business(client, "Tenant A")
    b = _business(client, "Tenant B")
    cash_a = _account(client, a["id"], "1000", "Cash", "asset")
    recv_a = _account(client, a["id"], "1100", "AR", "asset")
    rev_a = _account(client, a["id"], "4000", "Revenue", "revenue")
    exp_a = _account(client, a["id"], "6000", "Expense", "expense")
    _account(client, b["id"], "1000", "Cash", "asset")
    customer_a = _customer(client, a["id"])
    inv_a = _invoice(client, a["id"], customer_a["id"], "INV-A", "2026-01-01", "2026-01-31", 700, recv_a["id"], rev_a["id"])
    client.post("/api/payroll/employees", json={"business_id": a["id"], "name": "Alice", "pay_type": "hourly", "rate": 20})
    client.post("/api/inventory/items", json={"business_id": a["id"], "sku": "W-A", "name": "Widget A", "unit_cost": 5, "unit_price": 10})
    asset_a = client.post("/api/accounting/depreciation-assets", json={
        "business_id": a["id"], "name": "Machine", "asset_account_id": cash_a["id"],
        "accumulated_account_id": recv_a["id"], "depreciation_account_id": exp_a["id"],
        "cost": 1000, "useful_life_months": 10, "method": "straight_line",
        "acquisition_date": "2026-01-01", "start_date": "2026-01-01",
    }).get_json()

    # Nothing from A leaks into B's module lists.
    assert client.get(f"/api/accounting/invoices?business_id={b['id']}").get_json() == []
    assert client.get(f"/api/payroll/employees?business_id={b['id']}").get_json() == []
    assert client.get(f"/api/inventory/items?business_id={b['id']}").get_json() == []
    assert client.get(f"/api/accounting/depreciation-assets?business_id={b['id']}").get_json() == []

    # A user with no access to A cannot act on A's objects from any module.
    client_b = app.test_client()
    client_b.post("/api/auth/register", json={"username": "outsider", "password": "pw12345"})
    client_b.post("/api/auth/login", json={"username": "outsider", "password": "pw12345"})
    assert client_b.get(f"/api/accounting/invoices/{inv_a['id']}").status_code in (403, 404)
    assert client_b.post("/api/accounting/payments", json={"invoice_id": inv_a["id"], "payment_date": "2026-01-15", "amount": 100, "cash_account_id": cash_a["id"]}).status_code in (400, 403, 404)
    assert client_b.post(f"/api/accounting/depreciation-assets/{asset_a['id']}/post", json={"through_date": "2026-01-31"}).status_code in (400, 403, 404)
    assert client_b.post("/api/accounting/credit-notes", json={
        "business_id": a["id"], "invoice_id": inv_a["id"], "credit_number": "CN-X",
        "credit_date": "2026-01-15", "amount": 50,
    }).status_code in (400, 403, 404)
    # A's invoice remains untouched by the rejected cross-tenant attempts.
    detail = client.get(f"/api/accounting/invoices/{inv_a['id']}?business_id={a['id']}").get_json()
    assert detail["amount_paid"] == 0 and detail["status"] == "open"
    assert _tb(client, a["id"])["balanced"] is True
    assert _tb(client, b["id"])["total_debits"] == 0
