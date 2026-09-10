import pytest

from tax.calculator import calculate_personal_return


def test_2025_single_federal_estimate_uses_progressive_brackets():
    result = calculate_personal_return({"tax_year": 2025, "filing_status": "single", "wages": 60000})
    assert result["adjusted_gross_income"] == 60000
    assert result["deduction"] == 15750
    assert result["taxable_income"] == 44250
    assert result["federal_tax"] == 5071.5
    assert result["federal_refund_or_due"] == -5071.5


def test_itemized_deductions_credits_and_payments():
    result = calculate_personal_return({
        "tax_year": 2025,
        "filing_status": "married_joint",
        "wages": 100000,
        "itemized_deductions": 40000,
        "credits": 2000,
        "federal_withholding": 10000,
        "estimated_payments": 500,
        "state_tax_liability": 3000,
        "state_withholding": 3500,
    })
    assert result["deduction"] == 40000
    assert result["taxable_income"] == 60000
    assert result["federal_tax"] == 4723
    assert result["federal_refund_or_due"] == 5777
    assert result["state_refund_or_due"] == 500


def test_unsupported_year_and_negative_amount_rejected():
    with pytest.raises(ValueError, match="not supported"):
        calculate_personal_return({"tax_year": 2024, "filing_status": "single"})
    with pytest.raises(ValueError, match="cannot be negative"):
        calculate_personal_return({"tax_year": 2025, "filing_status": "single", "wages": -1})


def test_create_update_and_list_personal_return(client):
    taxpayer = client.post("/api/entities/taxpayers", json={"legal_name": "Taylor Reed", "filing_status": "single", "residence_state": "FL"}).get_json()
    response = client.post("/api/tax/returns", json={
        "taxpayer_id": taxpayer["id"], "tax_year": 2025, "wages": 60000, "federal_withholding": 6000,
    })
    assert response.status_code == 201
    filing = response.get_json()
    assert filing["federal_refund_or_due"] == 928.5
    listed = client.get("/api/tax/returns").get_json()
    assert listed[0]["taxpayer_name"] == "Taylor Reed"

    filing["credits"] = 1000
    updated = client.put(f"/api/tax/returns/{filing['id']}", json=filing)
    assert updated.status_code == 200
    assert updated.get_json()["federal_refund_or_due"] == 1928.5


def test_duplicate_person_year_rejected(client):
    taxpayer = client.post("/api/entities/taxpayers", json={"legal_name": "One Return"}).get_json()
    payload = {"taxpayer_id": taxpayer["id"], "tax_year": 2025}
    assert client.post("/api/tax/returns", json=payload).status_code == 201
    assert client.post("/api/tax/returns", json=payload).status_code == 400


def test_tax_returns_require_admin_for_writes(app):
    anon = app.test_client()
    assert anon.get("/api/tax/returns").status_code == 401
    assert anon.post("/api/tax/returns", json={}).status_code == 401
