"""Tenant isolation tests: users only reach businesses they were granted.

Model: ``user_business_access`` grants roles viewer < editor < owner per
business. Missing or foreign resources answer 404; insufficient role on an
accessible business answers 403.
"""


def _register(client, username, password="pw12345", role=None):
    payload = {"username": username, "password": password}
    if role:
        payload["role"] = role
    client.post("/api/auth/register", json=payload)
    client.post("/api/auth/login", json={"username": username, "password": password})


def _make_business(client, name):
    response = client.post("/api/entities/businesses", json={"legal_name": name})
    assert response.status_code == 201
    return response.get_json()


def _make_account(client, business_id, code, account_type="asset"):
    response = client.post(
        "/api/accounting/accounts",
        json={"business_id": business_id, "code": code, "name": code, "account_type": account_type},
    )
    assert response.status_code == 201
    return response.get_json()


def _make_contact(client, business_id, name="Customer"):
    response = client.post(
        "/api/accounting/contacts",
        json={"business_id": business_id, "name": name, "contact_type": "customer"},
    )
    assert response.status_code == 201
    return response.get_json()


def _make_invoice(client, business_id, customer_id, receivable_id, revenue_id):
    response = client.post(
        "/api/accounting/invoices",
        json={
            "business_id": business_id,
            "customer_id": customer_id,
            "invoice_number": "INV-1",
            "issue_date": "2026-01-10",
            "due_date": "2026-02-10",
            "description": "Work",
            "amount": 100,
            "receivable_account_id": receivable_id,
            "revenue_account_id": revenue_id,
        },
    )
    assert response.status_code == 201
    return response.get_json()


def _two_tenants(app):
    """Return (client_a, business_a, client_b, business_b) for two users."""
    client_a = app.test_client()
    _register(client_a, "alice")
    business_a = _make_business(client_a, "Alpha LLC")

    client_b = app.test_client()
    _register(client_b, "bob")
    business_b = _make_business(client_b, "Beta LLC")
    return client_a, business_a, client_b, business_b


def test_businesses_list_only_shows_accessible(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    assert [b["id"] for b in client_a.get("/api/entities/businesses").get_json()] == [business_a["id"]]
    assert [b["id"] for b in client_b.get("/api/entities/businesses").get_json()] == [business_b["id"]]


def test_cannot_read_foreign_business_collections(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    assert client_a.get(f"/api/accounting/accounts?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/invoices?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/expenses?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/inventory/items?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/cost-centers?business_id={business_b['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/reports/profit-loss?business_id={business_b['id']}").status_code == 404


def test_cannot_write_to_foreign_business(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    response = client_a.post(
        "/api/accounting/accounts",
        json={"business_id": business_b["id"], "code": "9999", "name": "Nope", "account_type": "asset"},
    )
    assert response.status_code == 404
    response = client_a.post(
        "/api/cost-centers",
        json={"business_id": business_b["id"], "code": "X", "name": "Nope"},
    )
    assert response.status_code == 404


def test_idor_read_and_modify_foreign_records(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    receivable = _make_account(client_b, business_b["id"], "1100")
    revenue = _make_account(client_b, business_b["id"], "4000", "revenue")
    contact = _make_contact(client_b, business_b["id"])
    invoice = _make_invoice(client_b, business_b["id"], contact["id"], receivable["id"], revenue["id"])
    cost_center = client_b.post(
        "/api/cost-centers",
        json={"business_id": business_b["id"], "code": "OPS", "name": "Ops"},
    ).get_json()

    assert client_a.get(f"/api/accounting/invoices/{invoice['id']}").status_code == 404
    assert client_a.get(f"/api/accounting/invoices/{invoice['id']}/print").status_code == 404
    assert client_a.put(f"/api/accounting/invoices/{invoice['id']}/void").status_code == 404
    assert client_a.delete(f"/api/cost-centers/{cost_center['id']}").status_code == 404

    # The record still exists and is untouched for its owner.
    assert client_b.get(f"/api/accounting/invoices/{invoice['id']}").status_code == 200


def test_cross_tenant_resource_reference_rejected(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    foreign_account = _make_account(client_b, business_b["id"], "1000")
    own_credit = _make_account(client_a, business_a["id"], "4000", "revenue")

    response = client_a.post(
        "/api/accounting/entries",
        json={
            "business_id": business_a["id"],
            "entry_date": "2026-01-15",
            "description": "Sneaky entry",
            "lines": [
                {"account_id": foreign_account["id"], "debit": 10},
                {"account_id": own_credit["id"], "credit": 10},
            ],
        },
    )
    assert response.status_code == 404
    assert client_a.get(f"/api/accounting/entries?business_id={business_a['id']}").get_json() == []


def test_viewer_cannot_write_but_editor_can(app):
    client_a, business_a, client_b, _ = _two_tenants(app)

    # Grant bob viewer on Alpha LLC.
    response = client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "viewer"},
    )
    assert response.status_code == 201

    assert client_b.get(f"/api/accounting/accounts?business_id={business_a['id']}").status_code == 200
    response = client_b.post(
        "/api/accounting/accounts",
        json={"business_id": business_a["id"], "code": "2000", "name": "Denied", "account_type": "asset"},
    )
    assert response.status_code == 403

    # Promote to editor: writes now succeed.
    response = client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "editor"},
    )
    assert response.status_code == 201
    response = client_b.post(
        "/api/accounting/accounts",
        json={"business_id": business_a["id"], "code": "2000", "name": "Allowed", "account_type": "asset"},
    )
    assert response.status_code == 201

    # Revoke entirely: even reads are rejected.
    response = client_a.delete(f"/api/entities/businesses/{business_a['id']}/access/2")
    assert response.status_code == 200
    assert client_b.get(f"/api/accounting/accounts?business_id={business_a['id']}").status_code == 404


def test_non_owner_cannot_manage_access(app):
    client_a, business_a, client_b, _ = _two_tenants(app)
    client_a.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "viewer"},
    )
    # Bob is a viewer on Alpha: he cannot grant or revoke.
    response = client_b.post(
        f"/api/entities/businesses/{business_a['id']}/access",
        json={"user_id": 2, "role": "owner"},
    )
    assert response.status_code == 403
    response = client_b.delete(f"/api/entities/businesses/{business_a['id']}/access/1")
    assert response.status_code == 403
    # Bob cannot even list Alpha's grants.
    assert client_b.get(f"/api/entities/businesses/{business_a['id']}/access").status_code == 403
    # Owner sees the grants.
    grants = client_a.get(f"/api/entities/businesses/{business_a['id']}/access").get_json()
    assert {g["user_id"] for g in grants} == {1, 2}


def test_cannot_revoke_last_owner(app):
    client_a, business_a, _, _ = _two_tenants(app)
    response = client_a.delete(f"/api/entities/businesses/{business_a['id']}/access/1")
    assert response.status_code == 400


def test_business_creation_grants_creator_owner(app):
    client = app.test_client()
    _register(client, "owner1")
    business = _make_business(client, "Mine LLC")
    grants = client.get(f"/api/entities/businesses/{business['id']}/access").get_json()
    assert grants[0]["role"] == "owner"


def test_dashboard_overview_excludes_foreign_businesses(app):
    client_a, business_a, client_b, business_b = _two_tenants(app)
    _make_account(client_b, business_b["id"], "1000")
    _make_account(client_b, business_b["id"], "4000", "revenue")

    data = client_a.get("/api/dashboard/overview").get_json()
    assert data["counts"]["businesses"] == 1
    assert data["counts"]["accounts"] == 0

    _make_account(client_a, business_a["id"], "1000")
    data = client_a.get("/api/dashboard/overview").get_json()
    assert data["counts"]["accounts"] == 1
