from .helpers import random_password
from .test_accounting import _account, _business


def _entry(client, business_id, entry_date, description, lines):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def test_audit_log_records_accounting_writes(client):
    business = _business(client, "Audit LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    _entry(client, business["id"], "2026-01-01", "Capital contribution", [{"account_id": cash["id"], "debit": 5000}, {"account_id": equity["id"], "credit": 5000}])
    log = client.get("/api/audit/log").get_json()
    assert len(log) >= 1
    entry = log[0]
    assert entry["module"] == "accounting"
    assert entry["action"] == "create"
    assert entry["username"] == "testuser"
    assert "Capital contribution" in entry["description"]


def test_audit_log_records_budget_operations(client):
    business = _business(client, "Budget Audit LLC")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    budget = client.post("/api/accounting/budgets", json={
        "business_id": business["id"], "account_id": revenue["id"], "fiscal_year": 2026,
        "period": "annual", "budgeted_amount": 10000,
    }).get_json()
    client.put(f"/api/accounting/budgets/{budget['id']}", json={"budgeted_amount": 15000})
    client.delete(f"/api/accounting/budgets/{budget['id']}")
    log = client.get("/api/audit/log").get_json()
    actions = [e["action"] for e in log if e["entity_type"] == "budget"]
    assert "create" in actions
    assert "update" in actions
    assert "delete" in actions


def test_audit_log_filter_by_module(client):
    business = _business(client, "Filter LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    _entry(client, business["id"], "2026-01-01", "Test", [{"account_id": cash["id"], "debit": 100}, {"account_id": equity["id"], "credit": 100}])
    log = client.get("/api/audit/log?module=accounting").get_json()
    assert all(e["module"] == "accounting" for e in log)
    assert len(log) >= 1


def test_audit_log_requires_admin(app):
    client = app.test_client()
    client.post("/api/auth/register", json={"username": "viewer1", "password": "pass1234", "role": "viewer"})
    client.post("/api/auth/login", json={"username": "viewer1", "password": "pass1234"})
    assert client.get("/api/audit/log").status_code == 403


def test_audit_log_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/audit/log").status_code == 401


def test_audit_log_limit(client):
    business = _business(client, "Limit LLC")
    cash = _account(client, business["id"], "1000", "Cash", "asset")
    equity = _account(client, business["id"], "3000", "Equity", "equity")
    for i in range(5):
        _entry(client, business["id"], "2026-01-01", f"Entry {i}", [{"account_id": cash["id"], "debit": 10}, {"account_id": equity["id"], "credit": 10}])
    log = client.get("/api/audit/log?limit=3").get_json()
    assert len(log) == 3


def _auth_entries(client):
    return client.get("/api/audit/log?module=auth").get_json()


def test_audit_records_login_success(app):
    password = random_password()
    anon = app.test_client()
    anon.post("/api/auth/register", json={"username": "loginuser", "password": password, "role": "admin"})
    anon.post("/api/auth/login", json={"username": "loginuser", "password": password})
    entries = _auth_entries(anon)
    logins = [e for e in entries if e["action"] == "login" and e["username"] == "loginuser"]
    assert len(logins) == 1
    assert logins[0]["entity_type"] == "user"


def test_audit_records_login_failure(app):
    admin_pw = random_password()
    admin = app.test_client()
    admin.post("/api/auth/register", json={"username": "audadmin", "password": admin_pw, "role": "admin"})
    anon = app.test_client()
    anon.post("/api/auth/register", json={"username": "victim", "password": random_password()})
    resp = anon.post("/api/auth/login", json={"username": "victim", "password": random_password()})
    assert resp.status_code == 401
    admin.post("/api/auth/login", json={"username": "audadmin", "password": admin_pw})
    entries = _auth_entries(admin)
    failures = [e for e in entries if e["action"] == "login_failed" and "victim" in e["description"]]
    assert len(failures) == 1
    assert failures[0]["user_id"] is None


def test_audit_records_rate_limited_login(app):
    admin_pw = random_password()
    admin = app.test_client()
    admin.post("/api/auth/register", json={"username": "rladmin", "password": admin_pw, "role": "admin"})
    anon = app.test_client()
    anon.post("/api/auth/register", json={"username": "rluser", "password": random_password()})
    for _ in range(5):
        assert anon.post("/api/auth/login", json={"username": "rluser", "password": random_password()}).status_code == 401
    assert anon.post("/api/auth/login", json={"username": "rluser", "password": random_password()}).status_code == 429
    admin.post("/api/auth/login", json={"username": "rladmin", "password": admin_pw})
    entries = _auth_entries(admin)
    assert any(e["action"] == "login_rate_limited" and "rluser" in e["description"] for e in entries)


def test_audit_records_logout(app):
    password = random_password()
    admin = app.test_client()
    admin.post("/api/auth/register", json={"username": "outadmin", "password": password, "role": "admin"})
    admin.post("/api/auth/login", json={"username": "outadmin", "password": password})
    assert admin.post("/api/auth/logout").status_code == 200
    admin.post("/api/auth/login", json={"username": "outadmin", "password": password})
    entries = _auth_entries(admin)
    assert any(e["action"] == "logout" and e["username"] == "outadmin" for e in entries)


def test_audit_records_admin_user_creation(client):
    resp = client.post("/api/auth/register", json={"username": "madebyadmin", "password": random_password(), "role": "viewer"})
    assert resp.status_code == 201
    new_id = resp.get_json()["id"]
    entries = _auth_entries(client)
    created = [e for e in entries if e["action"] == "create" and e["entity_id"] == new_id]
    assert len(created) == 1
    assert created[0]["username"] == "testuser"
    assert "madebyadmin" in created[0]["description"]


def test_audit_records_self_registration_without_actor(app):
    admin_pw = random_password()
    anon = app.test_client()
    admin = app.test_client()
    admin.post("/api/auth/register", json={"username": "sra", "password": admin_pw, "role": "admin"})
    anon.post("/api/auth/register", json={"username": "selfreg", "password": random_password()})
    admin.post("/api/auth/login", json={"username": "sra", "password": admin_pw})
    entries = _auth_entries(admin)
    created = [e for e in entries if e["action"] == "create" and "selfreg" in e["description"]]
    assert len(created) == 1
    assert created[0]["user_id"] is None


def test_audit_records_role_change(client):
    resp = client.post("/api/auth/register", json={"username": "roletarget", "password": random_password(), "role": "viewer"})
    target_id = resp.get_json()["id"]
    assert client.put(f"/api/auth/users/{target_id}/role", json={"role": "admin"}).status_code == 200
    entries = _auth_entries(client)
    changes = [e for e in entries if e["action"] == "update" and e["entity_id"] == target_id]
    assert len(changes) == 1
    assert "viewer" in changes[0]["description"] and "admin" in changes[0]["description"]


def test_audit_role_change_records_committed_previous_role(client):
    resp = client.post("/api/auth/register", json={"username": "seqtarget", "password": random_password(), "role": "viewer"})
    target_id = resp.get_json()["id"]
    assert client.put(f"/api/auth/users/{target_id}/role", json={"role": "admin"}).status_code == 200
    assert client.put(f"/api/auth/users/{target_id}/role", json={"role": "viewer"}).status_code == 200
    entries = _auth_entries(client)
    changes = [e for e in entries if e["action"] == "update" and e["entity_id"] == target_id]
    # Ordered newest first: each entry must reflect the role actually
    # committed by the immediately preceding update.
    assert len(changes) == 2
    assert "'admin' to 'viewer'" in changes[0]["description"]
    assert "'viewer' to 'admin'" in changes[1]["description"]


def test_audit_records_user_delete(client):
    resp = client.post("/api/auth/register", json={"username": "goneuser", "password": random_password()})
    target_id = resp.get_json()["id"]
    assert client.delete(f"/api/auth/users/{target_id}").status_code == 200
    entries = _auth_entries(client)
    deletes = [e for e in entries if e["action"] == "delete" and e["entity_id"] == target_id]
    assert len(deletes) == 1
    assert deletes[0]["username"] == "testuser"
    assert "goneuser" in deletes[0]["description"]


def test_audit_records_self_delete_with_actor_username(client):
    # testuser creates a second admin, then deletes their own account while
    # another user remains. The audit entry must keep the actor's username
    # even though the actor's user row no longer exists (user_id NULL).
    other_pw = random_password()
    resp = client.post("/api/auth/register", json={"username": "secondadmin", "password": other_pw, "role": "admin"})
    assert resp.status_code == 201
    self_id = client.get("/api/auth/me").get_json()["id"]
    assert client.delete(f"/api/auth/users/{self_id}").status_code == 200
    assert client.post("/api/auth/login", json={"username": "secondadmin", "password": other_pw}).status_code == 200
    entries = _auth_entries(client)
    deletes = [e for e in entries if e["action"] == "delete" and e["entity_id"] == self_id]
    assert len(deletes) == 1
    assert deletes[0]["username"] == "testuser"
    assert deletes[0]["user_id"] is None


def test_audit_never_records_passwords(app):
    # These fixed sentinel values are intentional test data, not credentials:
    # the test proves the exact strings never appear in any audit field.
    anon = app.test_client()
    admin = app.test_client()
    admin.post("/api/auth/register", json={"username": "pwadmin", "password": "pw-admin-9z", "role": "admin"})
    anon.post("/api/auth/register", json={"username": "pwuser", "password": "pw-secret-9z"})
    anon.post("/api/auth/login", json={"username": "pwuser", "password": "pw-secret-9z"})
    anon.post("/api/auth/login", json={"username": "pwuser", "password": "pw-wrong-9z"})
    admin.post("/api/auth/login", json={"username": "pwadmin", "password": "pw-admin-9z"})
    import json as _json
    blob = _json.dumps(_auth_entries(admin))
    for secret in ("pw-secret-9z", "pw-wrong-9z", "pw-admin-9z"):
        assert secret not in blob


def test_audit_records_bootstrap_admin(app, tmp_path, monkeypatch):
    from app import create_app
    boot_pw = random_password()
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", boot_pw)
    app2 = create_app(test_config={"PAYROLL_DATABASE": str(tmp_path / "boot.db")})
    c = app2.test_client()
    resp = c.post("/api/auth/login", json={"username": "admin", "password": boot_pw})
    assert resp.status_code == 200
    entries = _auth_entries(c)
    created = [e for e in entries if e["action"] == "create" and "admin" in e["description"]]
    assert len(created) == 1
    assert created[0]["user_id"] is None
