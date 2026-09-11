from .test_accounting import _account, _business


def _setup(client, name="Inv LLC"):
    business = _business(client, name)
    inventory_acct = _account(client, business["id"], "1300", "Inventory", "asset")
    cogs_acct = _account(client, business["id"], "5000", "COGS", "expense")
    sales_acct = _account(client, business["id"], "4000", "Sales", "revenue")
    return business, inventory_acct, cogs_acct, sales_acct


def test_create_inventory_item(client):
    business, inv, cogs, sales = _setup(client)
    item = client.post("/api/inventory/items", json={
        "business_id": business["id"], "sku": "WIDGET-1", "name": "Widget",
        "unit_cost": 5.00, "unit_price": 10.00, "quantity_on_hand": 100,
        "reorder_point": 20, "inventory_account_id": inv["id"], "cogs_account_id": cogs["id"], "sales_account_id": sales["id"],
    }).get_json()
    assert item["sku"] == "WIDGET-1"
    assert item["unit_cost"] == 5.0
    assert item["quantity_on_hand"] == 100


def test_list_inventory_items(client):
    business, inv, cogs, sales = _setup(client)
    client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "W-1", "name": "Widget 1", "unit_cost": 5, "unit_price": 10})
    client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "W-2", "name": "Widget 2", "unit_cost": 3, "unit_price": 7})
    items = client.get(f"/api/inventory/items?business_id={business['id']}").get_json()
    assert len(items) == 2


def test_create_duplicate_sku_rejected(client):
    business, _, _, _ = _setup(client)
    client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "DUP", "name": "Item", "unit_cost": 1, "unit_price": 2})
    response = client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "DUP", "name": "Item 2", "unit_cost": 1, "unit_price": 2})
    assert response.status_code == 400


def test_update_inventory_item(client):
    business, _, _, _ = _setup(client)
    item = client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "UPD", "name": "Item", "unit_cost": 5, "unit_price": 10}).get_json()
    response = client.put(f"/api/inventory/items/{item['id']}", json={"unit_price": 15, "name": "Updated Item"})
    assert response.status_code == 200
    assert response.get_json()["unit_price"] == 15
    assert response.get_json()["name"] == "Updated Item"


def test_delete_inventory_item(client):
    business, _, _, _ = _setup(client)
    item = client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "DEL", "name": "Item", "unit_cost": 1, "unit_price": 2}).get_json()
    response = client.delete(f"/api/inventory/items/{item['id']}")
    assert response.status_code == 200
    items = client.get(f"/api/inventory/items?business_id={business['id']}").get_json()
    assert len(items) == 0


def test_record_purchase_movement(client):
    business, _, _, _ = _setup(client)
    item = client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "PUR", "name": "Item", "unit_cost": 5, "unit_price": 10, "quantity_on_hand": 50}).get_json()
    mv = client.post("/api/inventory/movements", json={
        "business_id": business["id"], "item_id": item["id"], "movement_type": "purchase",
        "quantity": 30, "unit_cost": 5, "reference": "PO-1", "movement_date": "2026-01-15",
    }).get_json()
    assert mv["movement_type"] == "purchase"
    # Check quantity increased
    items = client.get(f"/api/inventory/items?business_id={business['id']}").get_json()
    assert items[0]["quantity_on_hand"] == 80


def test_record_sale_movement(client):
    business, _, _, _ = _setup(client)
    item = client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "SAL", "name": "Item", "unit_cost": 5, "unit_price": 10, "quantity_on_hand": 50}).get_json()
    mv = client.post("/api/inventory/movements", json={
        "business_id": business["id"], "item_id": item["id"], "movement_type": "sale",
        "quantity": 20, "reference": "SO-1", "movement_date": "2026-01-20",
    }).get_json()
    assert mv["movement_type"] == "sale"
    items = client.get(f"/api/inventory/items?business_id={business['id']}").get_json()
    assert items[0]["quantity_on_hand"] == 30


def test_sale_insufficient_inventory_rejected(client):
    business, _, _, _ = _setup(client)
    item = client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "INS", "name": "Item", "unit_cost": 5, "unit_price": 10, "quantity_on_hand": 10}).get_json()
    response = client.post("/api/inventory/movements", json={"business_id": business["id"], "item_id": item["id"], "movement_type": "sale", "quantity": 50, "movement_date": "2026-01-20"})
    assert response.status_code == 400


def test_list_movements(client):
    business, _, _, _ = _setup(client)
    item = client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "MOV", "name": "Item", "unit_cost": 5, "unit_price": 10, "quantity_on_hand": 50}).get_json()
    client.post("/api/inventory/movements", json={"business_id": business["id"], "item_id": item["id"], "movement_type": "purchase", "quantity": 20, "movement_date": "2026-01-15"})
    client.post("/api/inventory/movements", json={"business_id": business["id"], "item_id": item["id"], "movement_type": "sale", "quantity": 10, "movement_date": "2026-01-20"})
    mvs = client.get(f"/api/inventory/movements?business_id={business['id']}").get_json()
    assert len(mvs) == 2


def test_low_stock_report(client):
    business, _, _, _ = _setup(client)
    client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "LOW", "name": "Low Item", "unit_cost": 5, "unit_price": 10, "quantity_on_hand": 5, "reorder_point": 10})
    client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "OK", "name": "OK Item", "unit_cost": 5, "unit_price": 10, "quantity_on_hand": 50, "reorder_point": 10})
    low = client.get(f"/api/inventory/low-stock?business_id={business['id']}").get_json()
    assert len(low) == 1
    assert low[0]["sku"] == "LOW"


def test_inventory_valuation(client):
    business, _, _, _ = _setup(client)
    client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "V1", "name": "Item 1", "unit_cost": 5, "unit_price": 10, "quantity_on_hand": 100})
    client.post("/api/inventory/items", json={"business_id": business["id"], "sku": "V2", "name": "Item 2", "unit_cost": 3, "unit_price": 7, "quantity_on_hand": 200})
    val = client.get(f"/api/inventory/valuation?business_id={business['id']}").get_json()
    assert val["item_count"] == 2
    assert val["total_cost_value"] == 1100  # 100*5 + 200*3
    assert val["total_retail_value"] == 2400  # 100*10 + 200*7
    assert val["potential_profit"] == 1300


def test_inventory_isolated_per_business(client):
    first, _, _, _ = _setup(client, "First Inv LLC")
    second, _, _, _ = _setup(client, "Second Inv LLC")
    client.post("/api/inventory/items", json={"business_id": first["id"], "sku": "ISO", "name": "Item", "unit_cost": 1, "unit_price": 2})
    i1 = client.get(f"/api/inventory/items?business_id={first['id']}").get_json()
    i2 = client.get(f"/api/inventory/items?business_id={second['id']}").get_json()
    assert len(i1) == 1
    assert len(i2) == 0


def test_inventory_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/inventory/items?business_id=1").status_code == 401
    assert client.post("/api/inventory/items", json={}).status_code == 401
