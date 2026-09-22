import auth
from csv_export import sanitize_csv_field

from .test_accounting import _account
from .test_accounting_operations import _setup as _acct_setup


def _contact(client, business_id, name, contact_type="customer", email=""):
    return client.post("/api/accounting/contacts", json={
        "business_id": business_id, "name": name, "contact_type": contact_type, "email": email,
    }).get_json()


def _invoice(client, business_id, customer_id, number, amount, receivable_id, revenue_id, description="Test"):
    return client.post("/api/accounting/invoices", json={
        "business_id": business_id, "customer_id": customer_id, "invoice_number": number,
        "issue_date": "2026-01-01", "due_date": "2026-01-31", "description": description,
        "amount": amount, "receivable_account_id": receivable_id, "revenue_account_id": revenue_id,
    }).get_json()


# --------------------------------------------------------------------------- #
# Stored XSS — printable invoice
# --------------------------------------------------------------------------- #


def test_print_invoice_escapes_stored_html(client):
    business = client.post("/api/entities/businesses", json={
        "legal_name": "<script>alert('biz')</script>",
        "dba_name": "<img src=x onerror=alert('dba')>",
        "entity_type": "llc",
    }).get_json()
    receivable = _account(client, business["id"], "1100", "AR", "asset")
    revenue = _account(client, business["id"], "4000", "Revenue", "revenue")
    customer = _contact(client, business["id"], "<svg onload=alert('cust')>", email="a@b.com\"><script>")
    inv = _invoice(
        client, business["id"], customer["id"], "INV-<b>1</b>", 1000,
        receivable["id"], revenue["id"], description="<script>alert('desc')</script>",
    )
    response = client.get(f"/api/accounting/invoices/{inv['id']}/print")
    assert response.status_code == 200
    assert "text/html" in response.content_type
    html = response.data.decode("utf-8")
    for payload in (
        "<script>alert('biz')</script>", "<img src=x onerror=alert('dba')>",
        "<svg onload=alert('cust')>", "a@b.com\"><script>",
        "INV-<b>1</b>", "<script>alert('desc')</script>",
    ):
        assert payload not in html
    assert "&lt;script&gt;alert(&#39;biz&#39;)&lt;/script&gt;" in html
    assert "INVOICE" in html


# --------------------------------------------------------------------------- #
# CSV injection
# --------------------------------------------------------------------------- #


def test_sanitize_csv_field_unit():
    assert sanitize_csv_field("=1+1") == "'=1+1"
    assert sanitize_csv_field("+cmd") == "'+cmd"
    assert sanitize_csv_field("-10") == "'-10"
    assert sanitize_csv_field("@SUM(A1)") == "'@SUM(A1)"
    assert sanitize_csv_field("  =x") == "'  =x"
    assert sanitize_csv_field("normal") == "normal"
    assert sanitize_csv_field("a=b") == "a=b"
    assert sanitize_csv_field(5) == 5
    assert sanitize_csv_field(None) is None


def test_accounting_csv_export_neutralizes_formula_fields(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    _account(client, business["id"], "7000", "=cmd|'/c calc'!A0", "expense")
    response = client.get(f"/api/accounting/export/trial-balance.csv?business_id={business['id']}")
    assert response.status_code == 200
    csv_text = response.data.decode("utf-8")
    assert "'=cmd|'/c calc'!A0" in csv_text
    for line in csv_text.splitlines():
        for cell in line.split(","):
            assert not cell.strip().startswith(("=", "+", "@"))


def test_payroll_csv_export_neutralizes_formula_fields(client):
    business = client.post("/api/entities/businesses", json={"legal_name": "Payroll Co", "entity_type": "llc"}).get_json()
    emp = client.post("/api/payroll/employees", json={
        "business_id": business["id"], "name": "=HYPERLINK(\"http://evil\")", "pay_type": "hourly", "rate": 25.0,
    }).get_json()
    period = client.post("/api/payroll/pay-periods", json={
        "business_id": business["id"], "start_date": "2026-09-01", "end_date": "2026-09-15",
    }).get_json()
    client.post("/api/payroll/payslips", json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40})
    response = client.get(f"/api/payroll/reports/{period['id']}/csv")
    assert response.status_code == 200
    csv_text = response.data.decode("utf-8")
    assert "'=HYPERLINK" in csv_text


def test_audit_csv_export_neutralizes_formula_fields(client):
    business, cash, receivable, revenue, _ = _acct_setup(client)
    customer = _contact(client, business["id"], "Buyer")
    _invoice(client, business["id"], customer["id"], "INV-1", 500,
             receivable["id"], revenue["id"], description="=cmd|'/c calc'!A0")
    response = client.get("/api/audit/log/export")
    assert response.status_code == 200
    csv_text = response.data.decode("utf-8")
    assert "'=cmd|'/c calc'!A0" in csv_text


# --------------------------------------------------------------------------- #
# Authentication hardening
# --------------------------------------------------------------------------- #


def test_registration_closed_after_bootstrap(app, monkeypatch):
    monkeypatch.delenv("ALLOW_REGISTRATION", raising=False)
    anon = app.test_client()
    # Bootstrap: the very first user may always register.
    resp = anon.post("/api/auth/register", json={"username": "first", "password": "pw"})
    assert resp.status_code == 201
    # Afterwards public registration is closed unless explicitly enabled.
    resp = anon.post("/api/auth/register", json={"username": "second", "password": "pw"})
    assert resp.status_code == 403


def test_registration_explicitly_enabled(app, monkeypatch):
    monkeypatch.setenv("ALLOW_REGISTRATION", "1")
    anon = app.test_client()
    assert anon.post("/api/auth/register", json={"username": "first", "password": "pw"}).status_code == 201
    assert anon.post("/api/auth/register", json={"username": "second", "password": "pw"}).status_code == 201


def test_disable_registration_env_blocks_bootstrap(app, monkeypatch):
    monkeypatch.setenv("DISABLE_REGISTRATION", "1")
    monkeypatch.setenv("ALLOW_REGISTRATION", "1")
    anon = app.test_client()
    resp = anon.post("/api/auth/register", json={"username": "first", "password": "pw"})
    assert resp.status_code == 403


def test_role_change_takes_effect_without_relogin(client, app):
    # An admin session may register another admin while registration is open.
    resp = client.post("/api/auth/register", json={"username": "admin2", "password": "pw", "role": "admin"})
    assert resp.status_code == 201
    admin2_id = resp.get_json()["id"]
    admin2 = app.test_client()
    assert admin2.post("/api/auth/login", json={"username": "admin2", "password": "pw"}).status_code == 200
    assert admin2.get("/api/auth/users").status_code == 200
    # Demote to viewer — the live session must lose admin rights at once.
    assert client.put(f"/api/auth/users/{admin2_id}/role", json={"role": "viewer"}).status_code == 200
    assert admin2.get("/api/auth/users").status_code == 403


def test_deleted_user_session_is_invalid(client, app):
    resp = client.post("/api/auth/register", json={"username": "gone", "password": "pw"})
    assert resp.status_code == 201
    user_id = resp.get_json()["id"]
    victim = app.test_client()
    assert victim.post("/api/auth/login", json={"username": "gone", "password": "pw"}).status_code == 200
    assert victim.get("/api/dashboard/overview").status_code == 200
    assert client.delete(f"/api/auth/users/{user_id}").status_code == 200
    assert victim.get("/api/dashboard/overview").status_code == 401
    assert victim.get("/api/entities/businesses").status_code == 401


def test_login_rate_limit(client, app, monkeypatch):
    monkeypatch.setattr(auth, "_LOGIN_MAX_FAILURES", 3)
    client.post("/api/auth/register", json={"username": "ratelimited", "password": "pw"})
    anon = app.test_client()
    for _ in range(3):
        resp = anon.post("/api/auth/login", json={"username": "ratelimited", "password": "bad"})
        assert resp.status_code == 401
    # The next attempt is refused even with the correct password.
    resp = anon.post("/api/auth/login", json={"username": "ratelimited", "password": "pw"})
    assert resp.status_code == 429
