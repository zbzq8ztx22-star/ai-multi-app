import json

from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def test_export_business_returns_json(client):
    business = _business(client, "Export Test LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    _entry(client, business["id"], "2026-01-01", "Sale", [{"account_id": cash["id"], "debit": 5000}, {"account_id": revenue["id"], "credit": 5000}])
    response = client.get(f"/api/backup/export/{business['id']}")
    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert "attachment" in response.headers.get("Content-Disposition", "")
    data = response.get_json()
    assert data["business"]["legal_name"] == "Export Test LLC"
    assert len(data["tables"]["accounts"]) == 2
    assert len(data["tables"]["journal_entries"]) == 1
    assert len(data["tables"]["journal_lines"]) == 2


def test_export_business_not_found(client):
    response = client.get("/api/backup/export/9999")
    assert response.status_code == 400


def test_import_business_creates_new_business(client):
    business = _business(client, "Source LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    _entry(client, business["id"], "2026-01-01", "Sale", [{"account_id": cash["id"], "debit": 3000}, {"account_id": revenue["id"], "credit": 3000}])
    export = client.get(f"/api/backup/export/{business['id']}").get_json()
    response = client.post("/api/backup/import", json=export)
    assert response.status_code == 201
    result = response.get_json()
    assert result["business_id"] != business["id"]
    # New business should have the same accounts and entries
    accounts = client.get(f"/api/accounting/accounts?business_id={result['business_id']}").get_json()
    assert len(accounts) == 2
    entries = client.get(f"/api/accounting/entries?business_id={result['business_id']}").get_json()
    assert len(entries) == 1


def test_import_invalid_format(client):
    response = client.post("/api/backup/import", json={"not_a_backup": True})
    assert response.status_code == 400


def test_backup_endpoints_require_admin(app):
    client = app.test_client()
    client.post("/api/auth/register", json={"username": "viewer1", "password": "pass1234", "role": "viewer"})
    client.post("/api/auth/login", json={"username": "viewer1", "password": "pass1234"})
    assert client.get("/api/backup/export/1").status_code == 403
    assert client.post("/api/backup/import", json={}).status_code == 403


def test_backup_endpoints_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/backup/export/1").status_code == 401
    assert client.post("/api/backup/import", json={}).status_code == 401
