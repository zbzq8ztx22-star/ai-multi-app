from .test_accounting import _account, _business


def _setup(client, name="Groups LLC"):
    business = _business(client, name)
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    receivable = _account(client, business["id"], "1100", "Accounts Receivable", "asset")
    return business, cash, receivable


def test_create_account_group(client):
    business, _, _ = _setup(client)
    group = client.post("/api/accounting/account-groups", json={
        "business_id": business["id"], "name": "Current Assets", "account_type": "asset", "display_order": 1,
    }).get_json()
    assert group["name"] == "Current Assets"
    assert group["account_type"] == "asset"
    assert group["display_order"] == 1


def test_list_account_groups(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Current Assets", "account_type": "asset", "display_order": 1})
    client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Fixed Assets", "account_type": "asset", "display_order": 2})
    groups = client.get(f"/api/accounting/account-groups?business_id={business['id']}").get_json()
    assert len(groups) == 2
    assert groups[0]["display_order"] <= groups[1]["display_order"]


def test_create_duplicate_group_rejected(client):
    business, _, _ = _setup(client)
    client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Current Assets", "account_type": "asset"})
    response = client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Current Assets", "account_type": "asset"})
    assert response.status_code == 400


def test_create_group_invalid_type(client):
    business, _, _ = _setup(client)
    response = client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Bad Group", "account_type": "invalid"})
    assert response.status_code == 400


def test_update_account_group(client):
    business, _, _ = _setup(client)
    group = client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Current Assets", "account_type": "asset", "display_order": 1}).get_json()
    response = client.put(f"/api/accounting/account-groups/{group['id']}", json={"name": "Liquid Assets", "display_order": 5})
    assert response.status_code == 200
    assert response.get_json()["name"] == "Liquid Assets"
    assert response.get_json()["display_order"] == 5


def test_delete_account_group(client):
    business, _, _ = _setup(client)
    group = client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Current Assets", "account_type": "asset"}).get_json()
    response = client.delete(f"/api/accounting/account-groups/{group['id']}")
    assert response.status_code == 200
    groups = client.get(f"/api/accounting/account-groups?business_id={business['id']}").get_json()
    assert len(groups) == 0


def test_assign_account_to_group(client):
    business, cash, receivable = _setup(client)
    group = client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Current Assets", "account_type": "asset"}).get_json()
    response = client.put(f"/api/accounting/accounts/{cash['id']}/assign-group", json={"group_id": group["id"]})
    assert response.status_code == 200
    assert response.get_json()["group_id"] == group["id"]


def test_assign_account_wrong_type_rejected(client):
    business, cash, _ = _setup(client)
    group = client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Revenue Group", "account_type": "revenue"}).get_json()
    response = client.put(f"/api/accounting/accounts/{cash['id']}/assign-group", json={"group_id": group["id"]})
    assert response.status_code == 400


def test_delete_group_unlinks_accounts(client):
    business, cash, _ = _setup(client)
    group = client.post("/api/accounting/account-groups", json={"business_id": business["id"], "name": "Current Assets", "account_type": "asset"}).get_json()
    client.put(f"/api/accounting/accounts/{cash['id']}/assign-group", json={"group_id": group["id"]})
    client.delete(f"/api/accounting/account-groups/{group['id']}")
    accounts = client.get(f"/api/accounting/accounts?business_id={business['id']}").get_json()
    cash_account = [a for a in accounts if a["code"] == "1000"][0]
    assert cash_account.get("group_id") is None


def test_account_groups_isolated_per_business(client):
    first, _, _ = _setup(client, "First LLC")
    second = _business(client, "Second LLC")
    client.post("/api/accounting/account-groups", json={"business_id": first["id"], "name": "Current Assets", "account_type": "asset"})
    g1 = client.get(f"/api/accounting/account-groups?business_id={first['id']}").get_json()
    g2 = client.get(f"/api/accounting/account-groups?business_id={second['id']}").get_json()
    assert len(g1) == 1
    assert len(g2) == 0


def test_account_groups_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/account-groups?business_id=1").status_code == 401
    assert client.post("/api/accounting/account-groups", json={}).status_code == 401
