from .test_accounting import _account, _business


def test_audit_log_csv_export(client):
    # Create an accounting operation to generate audit entries
    business = _business(client, "Audit Export LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-01-01", "description": "Test entry",
        "lines": [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}],
    })
    response = client.get("/api/audit/log/export")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers.get("Content-Disposition", "")
    lines = response.data.decode("utf-8").strip().split("\n")
    assert len(lines) >= 2
    assert "Username" in lines[0]
    assert "Action" in lines[0]
    assert "Module" in lines[0]


def test_audit_log_csv_export_with_module_filter(client):
    business = _business(client, "Filter Export LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-01-01", "description": "Test entry",
        "lines": [{"account_id": cash["id"], "debit": 100}, {"account_id": revenue["id"], "credit": 100}],
    })
    response = client.get("/api/audit/log/export?module=accounting")
    assert response.status_code == 200
    lines = response.data.decode("utf-8").strip().split("\n")
    assert len(lines) >= 2


def test_audit_log_csv_export_empty(client):
    response = client.get("/api/audit/log/export")
    assert response.status_code == 200
    lines = response.data.decode("utf-8").strip().split("\n")
    # Only header row when no entries
    assert len(lines) == 1


def test_audit_log_csv_export_requires_admin(app):
    client = app.test_client()
    client.post("/api/auth/register", json={"username": "viewer_audit", "password": "pass1234", "role": "viewer"})
    client.post("/api/auth/login", json={"username": "viewer_audit", "password": "pass1234"})
    assert client.get("/api/audit/log/export").status_code == 403


def test_audit_log_csv_export_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/audit/log/export").status_code == 401
