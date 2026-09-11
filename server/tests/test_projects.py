from .test_accounting import _account, _business
from .test_accounting_operations import _setup as _acct_setup


def _entry_with_cc(client, business_id, entry_date, description, lines):
    return client.post("/api/accounting/entries", json={
        "business_id": business_id, "entry_date": entry_date, "description": description, "lines": lines,
    })


def test_create_project(client):
    business = _business(client, "Proj LLC")
    proj = client.post("/api/accounting/projects", json={
        "business_id": business["id"], "code": "PROJ-1", "name": "Website Redesign",
        "start_date": "2026-01-01", "budgeted_revenue": 50000, "budgeted_cost": 30000,
    }).get_json()
    assert proj["code"] == "PROJ-1"
    assert proj["name"] == "Website Redesign"
    assert proj["status"] == "active"


def test_list_projects(client):
    business = _business(client, "List Proj LLC")
    client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "P1", "name": "Project 1", "start_date": "2026-01-01"})
    client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "P2", "name": "Project 2", "start_date": "2026-02-01"})
    projects = client.get(f"/api/accounting/projects?business_id={business['id']}").get_json()
    assert len(projects) == 2


def test_create_duplicate_project_rejected(client):
    business = _business(client, "Dup Proj LLC")
    client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "DUP", "name": "Project", "start_date": "2026-01-01"})
    response = client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "DUP", "name": "Project 2", "start_date": "2026-01-01"})
    assert response.status_code == 400


def test_update_project(client):
    business = _business(client, "Upd Proj LLC")
    proj = client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "UPD", "name": "Project", "start_date": "2026-01-01"}).get_json()
    response = client.put(f"/api/accounting/projects/{proj['id']}", json={"name": "Updated Project", "status": "completed", "budgeted_revenue": 10000})
    assert response.status_code == 200
    assert response.get_json()["name"] == "Updated Project"
    assert response.get_json()["status"] == "completed"
    assert response.get_json()["budgeted_revenue"] == 10000


def test_delete_project(client):
    business = _business(client, "Del Proj LLC")
    proj = client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "DEL", "name": "Project", "start_date": "2026-01-01"}).get_json()
    response = client.delete(f"/api/accounting/projects/{proj['id']}")
    assert response.status_code == 200
    projects = client.get(f"/api/accounting/projects?business_id={business['id']}").get_json()
    assert len(projects) == 0


def test_project_profitability_no_cost_center(client):
    business = _business(client, "Profit No CC LLC")
    proj = client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "P1", "name": "Project", "start_date": "2026-01-01", "budgeted_revenue": 50000, "budgeted_cost": 30000}).get_json()
    profit = client.get(f"/api/accounting/projects/{proj['id']}/profitability").get_json()
    assert profit["actual_revenue"] == 0
    assert profit["actual_cost"] == 0
    assert profit["budgeted_profit"] == 20000


def test_project_profitability_with_cost_center(client):
    business, cash, receivable, revenue, expense = _acct_setup(client)
    # Create cost center
    cc = client.post("/api/cost-centers", json={"business_id": business["id"], "code": "PROJ-CC", "name": "Project CC"}).get_json()
    # Create project linked to cost center
    proj = client.post("/api/accounting/projects", json={
        "business_id": business["id"], "code": "PROFIT-1", "name": "Profitable Project",
        "start_date": "2026-01-01", "budgeted_revenue": 10000, "budgeted_cost": 5000,
        "cost_center_id": cc["id"],
    }).get_json()
    # Post revenue entry linked to cost center
    response = client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-02-01", "description": "Project revenue",
        "lines": [{"account_id": cash["id"], "debit": 8000, "cost_center_id": cc["id"]}, {"account_id": revenue["id"], "credit": 8000, "cost_center_id": cc["id"]}],
    })
    assert response.status_code == 201
    # Post expense entry linked to cost center
    response = client.post("/api/accounting/entries", json={
        "business_id": business["id"], "entry_date": "2026-02-15", "description": "Project expense",
        "lines": [{"account_id": expense["id"], "debit": 3000, "cost_center_id": cc["id"]}, {"account_id": cash["id"], "credit": 3000, "cost_center_id": cc["id"]}],
    })
    assert response.status_code == 201
    profit = client.get(f"/api/accounting/projects/{proj['id']}/profitability").get_json()
    assert profit["actual_revenue"] == 8000
    assert profit["actual_cost"] == 3000
    assert profit["actual_profit"] == 5000
    assert profit["profit_margin"] == 62.5


def test_project_profitability_invalid_end_date(client):
    business = _business(client, "Bad Date Proj LLC")
    response = client.post("/api/accounting/projects", json={"business_id": business["id"], "code": "BAD", "name": "Project", "start_date": "2026-06-01", "end_date": "2026-01-01"})
    assert response.status_code == 400


def test_projects_isolated_per_business(client):
    first = _business(client, "First Proj LLC")
    second = _business(client, "Second Proj LLC")
    client.post("/api/accounting/projects", json={"business_id": first["id"], "code": "ISO", "name": "Project", "start_date": "2026-01-01"})
    p1 = client.get(f"/api/accounting/projects?business_id={first['id']}").get_json()
    p2 = client.get(f"/api/accounting/projects?business_id={second['id']}").get_json()
    assert len(p1) == 1
    assert len(p2) == 0


def test_projects_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/projects?business_id=1").status_code == 401
    assert client.post("/api/accounting/projects", json={}).status_code == 401
