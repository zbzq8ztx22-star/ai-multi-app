from .test_accounting import _account, _business


def _entry_with_cost_center(client, business_id, entry_date, description, lines):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })


def test_create_cost_center(client):
    business = _business(client, "CC LLC")
    cc = client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"}).get_json()
    assert cc["code"] == "ENG"
    assert cc["name"] == "Engineering"
    assert cc["active"] == 1


def test_list_cost_centers(client):
    business = _business(client, "List CC LLC")
    client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"})
    client.post("/api/cost-centers", json={"business_id": business["id"], "code": "SALES", "name": "Sales"})
    ccs = client.get(f"/api/cost-centers?business_id={business['id']}").get_json()
    assert len(ccs) == 2


def test_create_duplicate_cost_center_rejected(client):
    business = _business(client, "Dup CC LLC")
    client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"})
    response = client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"})
    assert response.status_code == 400


def test_update_cost_center(client):
    business = _business(client, "Update CC LLC")
    cc = client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"}).get_json()
    response = client.put(f"/api/cost-centers/{cc['id']}", json={"name": "R&D", "active": False})
    assert response.status_code == 200
    assert response.get_json()["name"] == "R&D"
    assert response.get_json()["active"] == 0


def test_delete_cost_center(client):
    business = _business(client, "Delete CC LLC")
    cc = client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"}).get_json()
    response = client.delete(f"/api/cost-centers/{cc['id']}")
    assert response.status_code == 200
    ccs = client.get(f"/api/cost-centers?business_id={business['id']}").get_json()
    assert len(ccs) == 0


def test_list_active_only(client):
    business = _business(client, "Active CC LLC")
    client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"})
    client.post("/api/cost-centers", json={"business_id": business["id"], "code": "OLD", "name": "Old Dept", "active": False})
    ccs = client.get(f"/api/cost-centers?business_id={business['id']}&active_only=true").get_json()
    assert len(ccs) == 1
    assert ccs[0]["code"] == "ENG"


def test_cost_center_summary(client):
    business = _business(client, "Summary CC LLC")
    cc = client.post("/api/cost-centers", json={"business_id": business["id"], "code": "ENG", "name": "Engineering"}).get_json()
    summary = client.get(f"/api/cost-centers/summary?business_id={business['id']}").get_json()
    assert len(summary) == 1
    assert summary[0]["code"] == "ENG"
    assert summary[0]["total_expenses"] == 0


def test_cost_centers_isolated_per_business(client):
    first = _business(client, "First CC LLC")
    second = _business(client, "Second CC LLC")
    client.post("/api/cost-centers", json={"business_id": first["id"], "code": "ENG", "name": "Engineering"})
    c1 = client.get(f"/api/cost-centers?business_id={first['id']}").get_json()
    c2 = client.get(f"/api/cost-centers?business_id={second['id']}").get_json()
    assert len(c1) == 1
    assert len(c2) == 0


def test_cost_centers_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/cost-centers?business_id=1").status_code == 401
    assert client.post("/api/cost-centers", json={}).status_code == 401
