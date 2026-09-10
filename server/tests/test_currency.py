from .test_accounting import _business


def test_create_currency(client):
    business = _business(client, "Currency LLC")
    cur = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "USD", "name": "US Dollar", "symbol": "$", "is_base": True}).get_json()
    assert cur["code"] == "USD"
    assert cur["is_base"] == 1


def test_create_duplicate_currency_rejected(client):
    business = _business(client, "Dup LLC")
    client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "EUR", "name": "Euro", "symbol": "€"})
    response = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "EUR", "name": "Euro", "symbol": "€"})
    assert response.status_code == 400


def test_only_one_base_currency(client):
    business = _business(client, "Base LLC")
    client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "USD", "name": "Dollar", "is_base": True})
    response = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "EUR", "name": "Euro", "is_base": True})
    assert response.status_code == 400


def test_list_currencies(client):
    business = _business(client, "List LLC")
    client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "USD", "name": "Dollar", "is_base": True})
    client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "EUR", "name": "Euro"})
    curs = client.get(f"/api/currency/currencies?business_id={business['id']}").get_json()
    assert len(curs) == 2
    assert curs[0]["is_base"] == 1  # base currency first


def test_set_exchange_rate(client):
    business = _business(client, "Rate LLC")
    usd = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "USD", "name": "Dollar", "is_base": True}).get_json()
    eur = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "EUR", "name": "Euro"}).get_json()
    rate = client.post("/api/currency/rates", json={"business_id": business["id"], "from_currency_id": eur["id"], "to_currency_id": usd["id"], "rate": 1.1, "rate_date": "2026-01-01"}).get_json()
    assert rate["rate"] == 1.1


def test_convert_same_currency(client):
    business = _business(client, "Same LLC")
    usd = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "USD", "name": "Dollar", "is_base": True}).get_json()
    result = client.get(f"/api/currency/convert?business_id={business['id']}&amount=100&from_currency_id={usd['id']}&to_currency_id={usd['id']}").get_json()
    assert result["amount"] == 100
    assert result["rate"] == 1.0


def test_convert_with_rate(client):
    business = _business(client, "Convert LLC")
    usd = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "USD", "name": "Dollar", "is_base": True}).get_json()
    eur = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "EUR", "name": "Euro"}).get_json()
    client.post("/api/currency/rates", json={"business_id": business["id"], "from_currency_id": eur["id"], "to_currency_id": usd["id"], "rate": 1.1, "rate_date": "2026-01-01"})
    result = client.get(f"/api/currency/convert?business_id={business['id']}&amount=100&from_currency_id={eur['id']}&to_currency_id={usd['id']}").get_json()
    assert result["amount"] == 110
    assert result["rate"] == 1.1


def test_convert_no_rate_found(client):
    business = _business(client, "NoRate LLC")
    usd = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "USD", "name": "Dollar", "is_base": True}).get_json()
    eur = client.post("/api/currency/currencies", json={"business_id": business["id"], "code": "EUR", "name": "Euro"}).get_json()
    response = client.get(f"/api/currency/convert?business_id={business['id']}&amount=100&from_currency_id={eur['id']}&to_currency_id={usd['id']}")
    assert response.status_code == 400


def test_currency_isolated_per_business(client):
    first = _business(client, "First LLC")
    second = _business(client, "Second LLC")
    client.post("/api/currency/currencies", json={"business_id": first["id"], "code": "USD", "name": "Dollar", "is_base": True})
    r1 = client.get(f"/api/currency/currencies?business_id={first['id']}").get_json()
    r2 = client.get(f"/api/currency/currencies?business_id={second['id']}").get_json()
    assert len(r1) == 1
    assert len(r2) == 0


def test_currency_endpoints_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/currency/currencies?business_id=1").status_code == 401
    assert client.post("/api/currency/currencies", json={}).status_code == 401
    assert client.get("/api/currency/rates?business_id=1").status_code == 401
    assert client.get("/api/currency/convert?business_id=1&amount=1&from_currency_id=1&to_currency_id=1").status_code == 401
