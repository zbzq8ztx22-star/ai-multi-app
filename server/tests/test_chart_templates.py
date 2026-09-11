from .test_accounting import _business


def test_list_chart_templates(client):
    templates = client.get("/api/accounting/chart-templates").get_json()
    assert len(templates) >= 4
    names = [t["template"] for t in templates]
    assert "sole_proprietor" in names
    assert "llc" in names
    assert "corporation" in names
    assert "nonprofit" in names


def test_get_chart_template(client):
    template = client.get("/api/accounting/chart-templates/llc").get_json()
    assert template["template"] == "llc"
    assert template["account_count"] > 0
    assert len(template["accounts"]) == template["account_count"]
    # Check structure
    acct = template["accounts"][0]
    assert "code" in acct
    assert "name" in acct
    assert "account_type" in acct


def test_get_invalid_template(client):
    response = client.get("/api/accounting/chart-templates/invalid")
    assert response.status_code == 400


def test_apply_chart_template(client):
    business = _business(client, "Template LLC")
    result = client.post(f"/api/accounting/chart-templates/llc/apply?business_id={business['id']}").get_json()
    assert result["created_count"] > 0
    assert result["skipped_count"] == 0
    # Verify accounts were created
    accounts = client.get(f"/api/accounting/accounts?business_id={business['id']}").get_json()
    assert len(accounts) == result["created_count"]


def test_apply_chart_template_skips_existing(client):
    business = _business(client, "Skip Template LLC")
    # Apply once
    client.post(f"/api/accounting/chart-templates/llc/apply?business_id={business['id']}")
    # Apply again - should skip all
    result = client.post(f"/api/accounting/chart-templates/llc/apply?business_id={business['id']}").get_json()
    assert result["created_count"] == 0
    assert result["skipped_count"] > 0


def test_apply_sole_proprietor_template(client):
    business = _business(client, "Sole Prop LLC")
    result = client.post(f"/api/accounting/chart-templates/sole_proprietor/apply?business_id={business['id']}").get_json()
    assert result["created_count"] > 0
    accounts = client.get(f"/api/accounting/accounts?business_id={business['id']}").get_json()
    # Should have owner's capital and draw
    names = [a["name"] for a in accounts]
    assert "Owner's Capital" in names
    assert "Owner's Draw" in names


def test_apply_corporation_template(client):
    business = _business(client, "Corp LLC")
    result = client.post(f"/api/accounting/chart-templates/corporation/apply?business_id={business['id']}").get_json()
    assert result["created_count"] > 0
    accounts = client.get(f"/api/accounting/accounts?business_id={business['id']}").get_json()
    names = [a["name"] for a in accounts]
    assert "Common Stock" in names
    assert "Dividends" in names


def test_apply_nonprofit_template(client):
    business = _business(client, "Nonprofit LLC")
    result = client.post(f"/api/accounting/chart-templates/nonprofit/apply?business_id={business['id']}").get_json()
    assert result["created_count"] > 0
    accounts = client.get(f"/api/accounting/accounts?business_id={business['id']}").get_json()
    names = [a["name"] for a in accounts]
    assert "Donation Revenue" in names
    assert "Fundraising Expense" in names


def test_apply_invalid_template(client):
    business = _business(client, "Bad Template LLC")
    response = client.post(f"/api/accounting/chart-templates/invalid/apply?business_id={business['id']}")
    assert response.status_code == 400


def test_apply_template_isolated_per_business(client):
    first = _business(client, "First Template LLC")
    second = _business(client, "Second Template LLC")
    client.post(f"/api/accounting/chart-templates/llc/apply?business_id={first['id']}")
    a1 = client.get(f"/api/accounting/accounts?business_id={first['id']}").get_json()
    a2 = client.get(f"/api/accounting/accounts?business_id={second['id']}").get_json()
    assert len(a1) > 0
    assert len(a2) == 0


def test_chart_templates_require_authentication(app):
    client = app.test_client()
    assert client.get("/api/accounting/chart-templates").status_code == 401
