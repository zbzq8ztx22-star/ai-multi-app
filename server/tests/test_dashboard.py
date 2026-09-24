from .test_accounting_operations import _setup as _accounting_setup


def _journal_entry(client, business_id, entry_date, description, lines, status="posted"):
    response = client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description,
        "status": status, "lines": lines,
    })
    assert response.status_code == 201
    return response.get_json()


def test_dashboard_overview_returns_zero_counts_for_empty_database(client):
    data = client.get("/api/dashboard/overview").get_json()
    assert data["counts"]["employees"] == 0
    assert data["counts"]["businesses"] == 0
    assert data["counts"]["tax_returns"] == 0
    assert data["counts"]["posted_entries"] == 0
    assert data["recent"]["payslips"] == []
    assert data["recent"]["entries"] == []
    assert data["recent"]["returns"] == []


def test_dashboard_reflects_payroll_activity(client):
    biz = client.post("/api/entities/businesses", json={
        "legal_name": "Payroll Co",
    }).get_json()["id"]
    employee = client.post("/api/payroll/employees", json={
        "business_id": biz,
        "name": "Jane Doe", "position": "Engineer", "pay_type": "salary",
        "pay_frequency": "biweekly", "rate": 60000, "state": "CA",
        "filing_status": "single",
    }).get_json()
    period = client.post("/api/payroll/pay-periods", json={
        "business_id": biz,
        "start_date": "2026-01-01", "end_date": "2026-01-14", "pay_date": "2026-01-15",
    }).get_json()
    response = client.post("/api/payroll/payslips", json={
        "employee_id": employee["id"], "period_id": period["id"], "regular_hours": 80,
    })
    assert response.status_code == 201
    data = client.get("/api/dashboard/overview").get_json()
    assert data["counts"]["employees"] == 1
    assert data["counts"]["pay_periods"] == 1
    assert data["counts"]["payslips"] == 1
    assert len(data["recent"]["payslips"]) == 1
    assert data["recent"]["payslips"][0]["employee_name"] == "Jane Doe"


def test_dashboard_reflects_accounting_activity(client):
    business, cash, _, revenue, _ = _accounting_setup(client)
    _journal_entry(client, business["id"], "2026-01-10", "Sale", [{"account_id": cash["id"], "debit": 500}, {"account_id": revenue["id"], "credit": 500}])
    data = client.get("/api/dashboard/overview").get_json()
    assert data["counts"]["businesses"] == 1
    assert data["counts"]["accounts"] >= 4
    assert data["counts"]["posted_entries"] == 1
    assert data["counts"]["draft_entries"] == 0
    assert len(data["recent"]["entries"]) == 1
    assert data["recent"]["entries"][0]["business_name"] == "Operations LLC"


def test_dashboard_reflects_tax_activity(client):
    taxpayer = client.post("/api/entities/taxpayers", json={
        "legal_name": "Tax Payer", "taxpayer_type": "individual", "filing_status": "single",
    }).get_json()
    client.post("/api/tax/returns", json={
        "taxpayer_id": taxpayer["id"], "tax_year": 2025, "wages": 50000, "federal_withholding": 5000,
    })
    data = client.get("/api/dashboard/overview").get_json()
    assert data["counts"]["taxpayers"] == 1
    assert data["counts"]["tax_returns"] == 1
    assert len(data["recent"]["returns"]) == 1
    assert data["recent"]["returns"][0]["taxpayer_name"] == "Tax Payer"


def test_dashboard_requires_authentication(app):
    client = app.test_client()
    assert client.get("/api/dashboard/overview").status_code == 401
