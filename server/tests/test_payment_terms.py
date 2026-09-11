from .test_accounting import _business


def test_create_payment_terms(client):
    business = _business(client, "PT LLC")
    pt = client.post("/api/accounting/payment-terms", json={
        "business_id": business["id"], "name": "Net 30", "net_days": 30,
    }).get_json()
    assert pt["name"] == "Net 30"
    assert pt["net_days"] == 30


def test_create_payment_terms_with_discount(client):
    business = _business(client, "Discount PT LLC")
    pt = client.post("/api/accounting/payment-terms", json={
        "business_id": business["id"], "name": "2/10 Net 30", "net_days": 30,
        "discount_percent": 2, "discount_days": 10,
    }).get_json()
    assert pt["discount_percent"] == 2
    assert pt["discount_days"] == 10


def test_list_payment_terms(client):
    business = _business(client, "List PT LLC")
    client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 30", "net_days": 30})
    client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 60", "net_days": 60})
    terms = client.get(f"/api/accounting/payment-terms?business_id={business['id']}").get_json()
    assert len(terms) == 2


def test_create_duplicate_payment_terms_rejected(client):
    business = _business(client, "Dup PT LLC")
    client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 30", "net_days": 30})
    response = client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 30", "net_days": 30})
    assert response.status_code == 400


def test_create_default_payment_terms(client):
    business = _business(client, "Default PT LLC")
    pt = client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 30", "net_days": 30, "is_default": True}).get_json()
    assert pt["is_default"] == 1


def test_only_one_default_payment_terms(client):
    business = _business(client, "One Default PT LLC")
    client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 30", "net_days": 30, "is_default": True})
    response = client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 60", "net_days": 60, "is_default": True})
    assert response.status_code == 400


def test_update_payment_terms(client):
    business = _business(client, "Update PT LLC")
    pt = client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 30", "net_days": 30}).get_json()
    response = client.put(f"/api/accounting/payment-terms/{pt['id']}", json={"net_days": 45, "name": "Net 45"})
    assert response.status_code == 200
    assert response.get_json()["net_days"] == 45
    assert response.get_json()["name"] == "Net 45"


def test_delete_payment_terms(client):
    business = _business(client, "Delete PT LLC")
    pt = client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Net 30", "net_days": 30}).get_json()
    response = client.delete(f"/api/accounting/payment-terms/{pt['id']}")
    assert response.status_code == 200
    terms = client.get(f"/api/accounting/payment-terms?business_id={business['id']}").get_json()
    assert len(terms) == 0


def test_payment_terms_invalid_net_days(client):
    business = _business(client, "Bad Days PT LLC")
    response = client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Bad", "net_days": -1})
    assert response.status_code == 400


def test_payment_terms_invalid_discount(client):
    business = _business(client, "Bad Discount PT LLC")
    response = client.post("/api/accounting/payment-terms", json={"business_id": business["id"], "name": "Bad", "net_days": 30, "discount_percent": 150})
    assert response.status_code == 400


def test_payment_terms_isolated_per_business(client):
    first = _business(client, "First PT LLC")
    second = _business(client, "Second PT LLC")
    client.post("/api/accounting/payment-terms", json={"business_id": first["id"], "name": "Net 30", "net_days": 30})
    t1 = client.get(f"/api/accounting/payment-terms?business_id={first['id']}").get_json()
    t2 = client.get(f"/api/accounting/payment-terms?business_id={second['id']}").get_json()
    assert len(t1) == 1
    assert len(t2) == 0


def test_payment_terms_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/payment-terms?business_id=1").status_code == 401
    assert client.post("/api/accounting/payment-terms", json={}).status_code == 401
