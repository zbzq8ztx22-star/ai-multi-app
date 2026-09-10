from .test_accounting import _account, _business


def _setup(client, name="Dep LLC"):
    business = _business(client, name)
    asset_acct = _account(client, business["id"], "1500", "Equipment", "asset")
    accum_acct = _account(client, business["id"], "1510", "Accumulated Depreciation", "asset")
    dep_acct = _account(client, business["id"], "6010", "Depreciation Expense", "expense")
    return business, asset_acct, accum_acct, dep_acct


def test_create_depreciation_asset(client):
    business, asset, accum, dep = _setup(client)
    asset_data = client.post("/api/accounting/depreciation-assets", json={
        "business_id": business["id"], "name": "Server",
        "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"],
        "cost": 12000, "salvage_value": 2000, "useful_life_months": 60,
        "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01",
    }).get_json()
    assert asset_data["name"] == "Server"
    assert asset_data["cost"] == 12000
    assert asset_data["status"] == "active"


def test_list_depreciation_assets(client):
    business, asset, accum, dep = _setup(client)
    client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Server", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": 12000, "salvage_value": 2000, "useful_life_months": 60, "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"})
    client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Furniture", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": 5000, "salvage_value": 0, "useful_life_months": 36, "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"})
    assets = client.get(f"/api/accounting/depreciation-assets?business_id={business['id']}").get_json()
    assert len(assets) == 2


def test_depreciation_schedule_straight_line(client):
    business, asset, accum, dep = _setup(client)
    asset_data = client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Server", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": 12000, "salvage_value": 2000, "useful_life_months": 12, "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"}).get_json()
    schedule = client.get(f"/api/accounting/depreciation-assets/{asset_data['id']}/schedule").get_json()
    assert len(schedule["schedule"]) == 12
    # Monthly depreciation should be (12000 - 2000) / 12 = 833.33
    assert schedule["schedule"][0]["depreciation"] == 833.33
    # Final book value should equal salvage value
    assert schedule["final_book_value"] == 2000


def test_depreciation_schedule_declining_balance(client):
    business, asset, accum, dep = _setup(client)
    asset_data = client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Equipment", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": 10000, "salvage_value": 1000, "useful_life_months": 24, "method": "declining_balance", "depreciation_rate": 24, "acquisition_date": "2026-01-01", "start_date": "2026-01-01"}).get_json()
    schedule = client.get(f"/api/accounting/depreciation-assets/{asset_data['id']}/schedule").get_json()
    assert len(schedule["schedule"]) > 0
    # First month depreciation should be 10000 * 0.24 / 12 = 200
    assert schedule["schedule"][0]["depreciation"] == 200
    # Book value should never go below salvage value
    assert all(s["book_value"] >= 1000 for s in schedule["schedule"])


def test_post_depreciation(client):
    business, asset, accum, dep = _setup(client)
    asset_data = client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Server", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": 12000, "salvage_value": 2000, "useful_life_months": 12, "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"}).get_json()
    result = client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/post", json={"through_date": "2026-03-31"}).get_json()
    assert result["posted"] is True
    assert result["amount"] > 0
    # Check trial balance is balanced
    tb = client.get(f"/api/accounting/trial-balance?business_id={business['id']}").get_json()
    assert tb["balanced"] is True


def test_post_depreciation_full(client):
    business, asset, accum, dep = _setup(client)
    asset_data = client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Server", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": 1200, "salvage_value": 0, "useful_life_months": 12, "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"}).get_json()
    client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/post", json={"through_date": "2026-12-31"})
    assets = client.get(f"/api/accounting/depreciation-assets?business_id={business['id']}").get_json()
    assert assets[0]["status"] == "fully_depreciated"


def test_create_depreciation_asset_invalid_cost(client):
    business, asset, accum, dep = _setup(client)
    response = client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Bad", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": -100, "salvage_value": 0, "useful_life_months": 12, "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"})
    assert response.status_code == 400


def test_create_depreciation_asset_invalid_method(client):
    business, asset, accum, dep = _setup(client)
    response = client.post("/api/accounting/depreciation-assets", json={"business_id": business["id"], "name": "Bad", "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"], "cost": 1000, "salvage_value": 0, "useful_life_months": 12, "method": "invalid", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"})
    assert response.status_code == 400


def test_depreciation_assets_isolated_per_business(client):
    first, asset1, accum1, dep1 = _setup(client, "First Dep LLC")
    second, asset2, accum2, dep2 = _setup(client, "Second Dep LLC")
    client.post("/api/accounting/depreciation-assets", json={"business_id": first["id"], "name": "Server", "asset_account_id": asset1["id"], "accumulated_account_id": accum1["id"], "depreciation_account_id": dep1["id"], "cost": 1000, "salvage_value": 0, "useful_life_months": 12, "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01"})
    a1 = client.get(f"/api/accounting/depreciation-assets?business_id={first['id']}").get_json()
    a2 = client.get(f"/api/accounting/depreciation-assets?business_id={second['id']}").get_json()
    assert len(a1) == 1
    assert len(a2) == 0


def test_depreciation_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/depreciation-assets?business_id=1").status_code == 401
    assert client.post("/api/accounting/depreciation-assets", json={}).status_code == 401
