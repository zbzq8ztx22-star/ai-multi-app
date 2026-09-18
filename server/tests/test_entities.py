def test_create_and_list_taxpayer_with_employee_link(client):
    biz = client.post(
        "/api/entities/businesses", json={"legal_name": "Link Co"}
    ).get_json()["id"]
    employee = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Ana Rivera", "pay_type": "hourly", "rate": 30},
    ).get_json()
    response = client.post(
        "/api/entities/taxpayers",
        json={
            "legal_name": "Ana Rivera",
            "employee_id": employee["id"],
            "filing_status": "hoh",
            "residence_state": "FL",
            "identifier_last4": "1234",
        },
    )
    assert response.status_code == 201
    taxpayer = response.get_json()
    assert taxpayer["employee_id"] == employee["id"]
    assert taxpayer["identifier_last4"] == "1234"
    assert client.get("/api/entities/taxpayers").get_json() == [taxpayer]


def test_taxpayer_rejects_full_identifier(client):
    response = client.post(
        "/api/entities/taxpayers",
        json={"legal_name": "Private Person", "identifier_last4": "123456789"},
    )
    assert response.status_code == 400


def test_create_and_list_business(client):
    response = client.post(
        "/api/entities/businesses",
        json={
            "legal_name": "Northwind LLC",
            "entity_type": "llc",
            "ein_last4": "9876",
            "formation_state": "DE",
            "accounting_method": "accrual",
        },
    )
    assert response.status_code == 201
    business = response.get_json()
    assert business["legal_name"] == "Northwind LLC"
    assert business["accounting_method"] == "accrual"
    assert client.get("/api/entities/businesses").get_json() == [business]


def test_entities_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/entities/taxpayers").status_code == 401
    assert client.post("/api/entities/businesses", json={"legal_name": "Nope"}).status_code == 401


def test_viewer_cannot_create_entities(app):
    client = app.test_client()
    client.post("/api/auth/register", json={"username": "first", "password": "pw", "role": "admin"})
    client.post("/api/auth/register", json={"username": "reader", "password": "pw"})
    client.post("/api/auth/login", json={"username": "reader", "password": "pw"})
    assert client.get("/api/entities/taxpayers").status_code == 200
    assert client.post("/api/entities/taxpayers", json={"legal_name": "Nope"}).status_code == 403
