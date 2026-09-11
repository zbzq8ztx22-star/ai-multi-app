from .test_accounting import _account, _business


def _setup(client, name="PO LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    expense = _account(client, business["id"], "6000", "Supplies", "expense")
    return business, cash, expense


def _po_data(business_id, cash_id, expense_id, po_number="PO-1"):
    return {
        "business_id": business_id,
        "po_number": po_number,
        "order_date": "2026-01-15",
        "expense_account_id": expense_id,
        "payment_account_id": cash_id,
        "lines": [
            {"description": "Office supplies", "quantity": 10, "unit_price": 5.00},
            {"description": "Printer paper", "quantity": 20, "unit_price": 3.50},
        ],
    }


def test_create_purchase_order(client):
    business, cash, expense = _setup(client)
    po = client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"])).get_json()
    assert po["po_number"] == "PO-1"
    assert po["total_amount"] == 120.0  # 10*5 + 20*3.5
    assert po["status"] == "draft"
    assert len(po["lines"]) == 2


def test_list_purchase_orders(client):
    business, cash, expense = _setup(client)
    client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"], "PO-1"))
    client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"], "PO-2"))
    pos = client.get(f"/api/accounting/purchase-orders?business_id={business['id']}").get_json()
    assert len(pos) == 2


def test_create_duplicate_po_rejected(client):
    business, cash, expense = _setup(client)
    client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"]))
    response = client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"]))
    assert response.status_code == 400


def test_update_po_status_to_sent(client):
    business, cash, expense = _setup(client)
    po = client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"])).get_json()
    response = client.put(f"/api/accounting/purchase-orders/{po['id']}/status", json={"status": "sent"})
    assert response.status_code == 200
    assert response.get_json()["status"] == "sent"


def test_update_po_status_to_received_creates_entry(client):
    business, cash, expense = _setup(client)
    po = client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"])).get_json()
    response = client.put(f"/api/accounting/purchase-orders/{po['id']}/status", json={"status": "received"})
    assert response.status_code == 200
    assert response.get_json()["status"] == "received"
    assert response.get_json()["journal_entry_id"] is not None
    # Trial balance should be balanced
    tb = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert tb["balanced"] is True


def test_received_po_cannot_change_status(client):
    business, cash, expense = _setup(client)
    po = client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"])).get_json()
    client.put(f"/api/accounting/purchase-orders/{po['id']}/status", json={"status": "received"})
    response = client.put(f"/api/accounting/purchase-orders/{po['id']}/status", json={"status": "draft"})
    assert response.status_code == 400


def test_delete_draft_po(client):
    business, cash, expense = _setup(client)
    po = client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"])).get_json()
    response = client.delete(f"/api/accounting/purchase-orders/{po['id']}")
    assert response.status_code == 200
    pos = client.get(f"/api/accounting/purchase-orders?business_id={business['id']}").get_json()
    assert len(pos) == 0


def test_delete_received_po_rejected(client):
    business, cash, expense = _setup(client)
    po = client.post("/api/accounting/purchase-orders", json=_po_data(business["id"], cash["id"], expense["id"])).get_json()
    client.put(f"/api/accounting/purchase-orders/{po['id']}/status", json={"status": "received"})
    response = client.delete(f"/api/accounting/purchase-orders/{po['id']}")
    assert response.status_code == 400


def test_create_po_with_vendor(client):
    business, cash, expense = _setup(client)
    vendor = client.post("/api/accounting/contacts", json={"business_id": business["id"], "name": "Supplier", "contact_type": "vendor"}).get_json()
    data = _po_data(business["id"], cash["id"], expense["id"])
    data["vendor_id"] = vendor["id"]
    po = client.post("/api/accounting/purchase-orders", json=data).get_json()
    assert po["vendor_id"] == vendor["id"]
    assert po["vendor_name"] == "Supplier"


def test_create_po_no_lines_rejected(client):
    business, cash, expense = _setup(client)
    data = _po_data(business["id"], cash["id"], expense["id"])
    data["lines"] = []
    response = client.post("/api/accounting/purchase-orders", json=data)
    assert response.status_code == 400


def test_purchase_orders_isolated_per_business(client):
    first, cash1, exp1 = _setup(client, "First PO LLC")
    second, cash2, exp2 = _setup(client, "Second PO LLC")
    client.post("/api/accounting/purchase-orders", json=_po_data(first["id"], cash1["id"], exp1["id"]))
    p1 = client.get(f"/api/accounting/purchase-orders?business_id={first['id']}").get_json()
    p2 = client.get(f"/api/accounting/purchase-orders?business_id={second['id']}").get_json()
    assert len(p1) == 1
    assert len(p2) == 0


def test_purchase_orders_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/purchase-orders?business_id=1").status_code == 401
    assert client.post("/api/accounting/purchase-orders", json={}).status_code == 401
