import datetime

from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines, status="posted"):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })


def _setup(client, name="Close LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    return business, cash, revenue


def test_close_period(client):
    business, _, _ = _setup(client)
    response = client.post("/api/accounting/closing-periods", json={
        "business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31",
        "closed_by": "admin", "notes": "Q1 close",
    })
    assert response.status_code == 201
    cp = response.get_json()
    assert cp["period_start"] == "2026-01-01"
    assert cp["period_end"] == "2026-03-31"
    assert cp["closed_by"] == "admin"


def test_list_closing_periods(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-04-01", "period_end": "2026-06-30"})
    periods = client.get(f"/api/accounting/closing-periods?business_id={business['id']}").get_json()
    assert len(periods) == 2
    assert periods[0]["period_end"] == "2026-06-30"  # most recent first


def test_closed_period_blocks_journal_entries(client):
    business, cash, revenue = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    response = _entry(client, business["id"], "2026-02-15", "Blocked entry", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}])
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()


def test_open_period_allows_journal_entries(client):
    business, cash, revenue = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    response = _entry(client, business["id"], "2026-05-15", "Allowed entry", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}])
    assert response.status_code == 201


def test_reopen_period(client):
    business, cash, revenue = _setup(client)
    cp = client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"}).get_json()
    # Entry should be blocked
    assert _entry(client, business["id"], "2026-02-15", "Blocked", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}]).status_code == 400
    # Reopen
    response = client.delete(f"/api/accounting/closing-periods/{cp['id']}")
    assert response.status_code == 200
    # Entry should now be allowed
    response = _entry(client, business["id"], "2026-02-15", "Allowed now", [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}])
    assert response.status_code == 201


def test_duplicate_close_rejected(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    response = client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    assert response.status_code == 400


def test_overlapping_periods_rejected(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-06-30"})
    response = client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-04-01", "period_end": "2026-09-30"})
    assert response.status_code == 400


def test_check_period_closed(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/closing-periods", json={"business_id": business["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    closed = client.get(f"/api/accounting/closing-periods/check?business_id={business['id']}&entry_date=2026-02-15").get_json()
    assert closed["closed"] is True
    open_result = client.get(f"/api/accounting/closing-periods/check?business_id={business['id']}&entry_date=2026-06-15").get_json()
    assert open_result["closed"] is False


def test_closing_periods_isolated_per_business(client):
    first, _, _ = _setup(client, "First LLC")
    second, _, _ = _setup(client, "Second LLC")
    client.post("/api/accounting/closing-periods", json={"business_id": first["id"], "period_start": "2026-01-01", "period_end": "2026-03-31"})
    p1 = client.get(f"/api/accounting/closing-periods?business_id={first['id']}").get_json()
    p2 = client.get(f"/api/accounting/closing-periods?business_id={second['id']}").get_json()
    assert len(p1) == 1
    assert len(p2) == 0


def test_closing_periods_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/closing-periods?business_id=1").status_code == 401
    assert client.post("/api/accounting/closing-periods", json={}).status_code == 401


def _full_setup(client, name="Close Ops LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    receivable = _account(client, business["id"], "1100", "AR", "asset")
    asset_acct = _account(client, business["id"], "1500", "Equipment", "asset")
    accum_acct = _account(client, business["id"], "1510", "Accumulated Depreciation", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    expense = _account(client, business["id"], "6000", "Expense", "expense")
    dep_expense = _account(client, business["id"], "6010", "Depreciation Expense", "expense")
    return business, cash, receivable, asset_acct, accum_acct, revenue, expense, dep_expense


def _close(client, business_id, start="2026-01-01", end="2026-03-31"):
    response = client.post("/api/accounting/closing-periods", json={
        "business_id": business_id, "period_start": start, "period_end": end,
    })
    assert response.status_code == 201


def _customer(client, business_id):
    return client.post("/api/accounting/contacts", json={
        "business_id": business_id, "name": "Buyer", "contact_type": "customer",
    }).get_json()


def _invoice(client, business_id, customer_id, issue_date, receivable_id, revenue_id, number="INV-1"):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": issue_date, "due_date": "2026-12-31", "description": "Test", "amount": 1000,
        "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    })


def _dep_asset(client, business_id, asset_id, accum_id, dep_id, name="Server"):
    return client.post("/api/accounting/depreciation-assets", json={
        "business_id": business_id, "name": name,
        "asset_account_id": asset_id, "accumulated_account_id": accum_id, "depreciation_account_id": dep_id,
        "cost": 12000, "salvage_value": 2000, "useful_life_months": 60,
        "method": "straight_line", "acquisition_date": "2025-01-01", "start_date": "2025-01-01",
    }).get_json()


def test_closed_period_blocks_invoice(client):
    business, _, receivable, _, _, revenue, _, _ = _full_setup(client, "Inv Close LLC")
    customer = _customer(client, business["id"])
    _close(client, business["id"])
    response = _invoice(client, business["id"], customer["id"], "2026-02-15", receivable["id"], revenue["id"])
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()


def test_closed_period_blocks_invoice_payment(client):
    business, cash, receivable, _, _, revenue, _, _ = _full_setup(client, "Pay Close LLC")
    customer = _customer(client, business["id"])
    invoice = _invoice(client, business["id"], customer["id"], "2026-02-15", receivable["id"], revenue["id"]).get_json()
    _close(client, business["id"])
    response = client.post("/api/accounting/payments", json={
        "invoice_id": invoice["id"], "amount": 1000, "payment_date": "2026-02-20", "cash_account_id": cash["id"],
    })
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()
    invoice = client.get(f"/api/accounting/invoices/{invoice['id']}").get_json()
    assert invoice["amount_paid"] == 0
    assert invoice["status"] == "open"


def test_closed_period_blocks_approved_expense(client):
    business, cash, _, _, _, _, expense, _ = _full_setup(client, "Exp Close LLC")
    _close(client, business["id"])
    response = client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "expense_date": "2026-02-15", "amount": 500,
        "description": "Blocked", "payment_account_id": cash["id"], "expense_account_id": expense["id"],
        "approval_status": "approved",
    })
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()


def test_closed_period_blocks_pending_expense_approval(client):
    business, cash, _, _, _, _, expense, _ = _full_setup(client, "Appr Close LLC")
    exp = client.post("/api/accounting/expenses", json={
        "business_id": business["id"], "expense_date": "2026-02-15", "amount": 500,
        "description": "Pending", "payment_account_id": cash["id"], "expense_account_id": expense["id"],
        "approval_status": "pending",
    }).get_json()
    _close(client, business["id"])
    response = client.put(f"/api/accounting/expenses/{exp['id']}/approve", json={"approver": "admin"})
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()
    exp = client.get(f"/api/accounting/expenses?business_id={business['id']}").get_json()[0]
    assert exp["approval_status"] == "pending"
    assert exp["journal_entry_id"] is None


def test_closed_period_blocks_credit_note(client):
    business, _, receivable, _, _, revenue, _, _ = _full_setup(client, "CN Close LLC")
    customer = _customer(client, business["id"])
    _close(client, business["id"])
    response = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-1",
        "credit_date": "2026-02-15", "amount": 500,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    })
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()


def test_closed_period_blocks_credit_note_void(client):
    business, _, receivable, _, _, revenue, _, _ = _full_setup(client, "Void CN LLC")
    customer = _customer(client, business["id"])
    cn = client.post("/api/accounting/credit-notes", json={
        "business_id": business["id"], "customer_id": customer["id"], "credit_number": "CN-V",
        "credit_date": "2026-01-15", "amount": 500,
        "receivable_account_id": receivable["id"], "revenue_account_id": revenue["id"],
    }).get_json()
    # Void posts a reversing entry dated today; close a period covering it
    _close(client, business["id"], "1999-01-01", "2099-12-31")
    response = client.put(f"/api/accounting/credit-notes/{cn['id']}/void?business_id={business['id']}")
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()
    cn = client.get(f"/api/accounting/credit-notes?business_id={business['id']}").get_json()[0]
    assert cn["status"] == "applied"


def test_closed_period_blocks_depreciation(client):
    business, _, _, asset_acct, accum, _, _, dep_expense = _full_setup(client, "Dep Close LLC")
    asset = _dep_asset(client, business["id"], asset_acct["id"], accum["id"], dep_expense["id"])
    _close(client, business["id"])
    response = client.post(f"/api/accounting/depreciation-assets/{asset['id']}/post", json={"through_date": "2026-03-31"})
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()


def test_closed_period_blocks_purchase_order_receiving(client):
    business, cash, _, _, _, _, expense, _ = _full_setup(client, "PO Close LLC")
    po = client.post("/api/accounting/purchase-orders", json={
        "business_id": business["id"], "po_number": "PO-1", "order_date": "2026-02-15",
        "expense_account_id": expense["id"], "payment_account_id": cash["id"],
        "lines": [{"description": "Supplies", "quantity": 10, "unit_price": 5.00}],
    }).get_json()
    _close(client, business["id"])
    response = client.put(f"/api/accounting/purchase-orders/{po['id']}/status", json={"status": "received"})
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()
    pos = client.get(f"/api/accounting/purchase-orders?business_id={business['id']}").get_json()
    assert pos[0]["status"] == "draft"


def test_closed_period_blocks_asset_disposal(client):
    business, _, _, asset_acct, accum, _, _, dep_expense = _full_setup(client, "Disp Close LLC")
    asset = _dep_asset(client, business["id"], asset_acct["id"], accum["id"], dep_expense["id"])
    gain_loss = _account(client, business["id"], "6100", "Gain/Loss", "expense")
    _close(client, business["id"])
    response = client.post(f"/api/accounting/depreciation-assets/{asset['id']}/dispose", json={
        "disposal_date": "2026-02-15", "disposal_price": 8000, "gain_loss_account_id": gain_loss["id"],
    })
    assert response.status_code == 400
    assert "closed" in response.get_json()["error"].lower()
    assets = client.get(f"/api/accounting/depreciation-assets?business_id={business['id']}").get_json()
    assert assets[0]["status"] == "active"
