from .test_accounting import _account, _business


def _setup(client, name="FAR LLC"):
    business = _business(client, name)
    asset_acct = _account(client, business["id"], "1500", "Equipment", "asset")
    accum_acct = _account(client, business["id"], "1510", "Accumulated Dep", "asset")
    dep_acct = _account(client, business["id"], "6010", "Depreciation Expense", "expense")
    gain_loss_acct = _account(client, business["id"], "7000", "Gain/Loss on Disposal", "revenue")
    return business, asset_acct, accum_acct, dep_acct, gain_loss_acct


def _create_asset(client, business, asset, accum, dep, name="Server", cost=12000, salvage=2000, life=12):
    return client.post("/api/accounting/depreciation-assets", json={
        "business_id": business["id"], "name": name,
        "asset_account_id": asset["id"], "accumulated_account_id": accum["id"], "depreciation_account_id": dep["id"],
        "cost": cost, "salvage_value": salvage, "useful_life_months": life,
        "method": "straight_line", "acquisition_date": "2026-01-01", "start_date": "2026-01-01",
    }).get_json()


def test_fixed_asset_register_empty(client):
    business = _business(client, "Empty FAR LLC")
    result = client.get(f"/api/accounting/reports/fixed-asset-register?business_id={business['id']}").get_json()
    assert result["total_assets"] == 0
    assert result["total_cost"] == 0
    assert result["total_book_value"] == 0


def test_fixed_asset_register_with_assets(client):
    business, asset, accum, dep, _ = _setup(client)
    _create_asset(client, business, asset, accum, dep, "Server", 12000, 2000, 12)
    _create_asset(client, business, asset, accum, dep, "Furniture", 5000, 0, 36)
    result = client.get(f"/api/accounting/reports/fixed-asset-register?business_id={business['id']}").get_json()
    assert result["total_assets"] == 2
    assert result["total_cost"] == 17000
    # No depreciation posted yet, so book value = cost
    assert result["total_book_value"] == 17000
    assert result["total_accumulated_depreciation"] == 0


def test_fixed_asset_register_with_depreciation(client):
    business, asset, accum, dep, _ = _setup(client)
    asset_data = _create_asset(client, business, asset, accum, dep, "Server", 12000, 2000, 12)
    # Post depreciation for 3 months
    client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/post", json={"through_date": "2026-03-31"})
    result = client.get(f"/api/accounting/reports/fixed-asset-register?business_id={business['id']}").get_json()
    assert result["total_assets"] == 1
    assert result["total_cost"] == 12000
    # 3 months of depreciation: (12000-2000)/12 = 833.33 * 3 = 2500
    assert result["total_accumulated_depreciation"] > 0
    assert result["total_book_value"] < result["total_cost"]


def test_dispose_fixed_asset(client):
    business, asset, accum, dep, gain_loss = _setup(client)
    asset_data = _create_asset(client, business, asset, accum, dep, "Server", 10000, 0, 12)
    result = client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/dispose", json={
        "disposal_date": "2026-06-30", "disposal_price": 8000, "gain_loss_account_id": gain_loss["id"],
    }).get_json()
    assert result["disposed"] is True
    assert result["book_value"] == 10000  # No depreciation posted
    assert result["gain_loss"] == -2000  # 8000 - 10000 = -2000 (loss)
    # Check asset is marked as disposed
    register = client.get(f"/api/accounting/reports/fixed-asset-register?business_id={business['id']}").get_json()
    assert register["assets"][0]["status"] == "disposed"


def test_dispose_fixed_asset_with_gain(client):
    business, asset, accum, dep, gain_loss = _setup(client)
    asset_data = _create_asset(client, business, asset, accum, dep, "Server", 10000, 0, 12)
    # Post depreciation first
    client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/post", json={"through_date": "2026-12-31"})
    result = client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/dispose", json={
        "disposal_date": "2027-01-15", "disposal_price": 2000, "gain_loss_account_id": gain_loss["id"],
    }).get_json()
    assert result["disposed"] is True
    # Book value should be 0 (fully depreciated), so gain = 2000
    assert result["book_value"] == 0
    assert result["gain_loss"] == 2000


def test_dispose_already_disposed_rejected(client):
    business, asset, accum, dep, gain_loss = _setup(client)
    asset_data = _create_asset(client, business, asset, accum, dep, "Server", 10000, 0, 12)
    client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/dispose", json={
        "disposal_date": "2026-06-30", "disposal_price": 5000, "gain_loss_account_id": gain_loss["id"],
    })
    response = client.post(f"/api/accounting/depreciation-assets/{asset_data['id']}/dispose", json={
        "disposal_date": "2026-07-30", "disposal_price": 3000, "gain_loss_account_id": gain_loss["id"],
    })
    assert response.status_code == 400


def test_fixed_asset_register_isolated_per_business(client):
    first, a1, ac1, d1, _ = _setup(client, "First FAR LLC")
    second, a2, ac2, d2, _ = _setup(client, "Second FAR LLC")
    _create_asset(client, first, a1, ac1, d1, "Server", 1000, 0, 12)
    r1 = client.get(f"/api/accounting/reports/fixed-asset-register?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/accounting/reports/fixed-asset-register?business_id={second['id']}").get_json()
    assert r1["total_assets"] == 1
    assert r2["total_assets"] == 0


def test_fixed_asset_register_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/reports/fixed-asset-register?business_id=1").status_code == 401
