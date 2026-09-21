from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from tests.helpers import MockResponse, _sse_event
from payroll.calculator import calculate_payslip


class FakeOpenExecSession:
    """Fake requests.Session that records calls and returns a fixed response."""

    def __init__(self, response):
        self.response = response
        self.calls = {}

    def post(self, url, **kwargs):
        self.calls["url"] = url
        self.calls["json"] = kwargs.get("json")
        self.calls["headers"] = kwargs.get("headers")
        return self.response


@pytest.fixture
def biz(client):
    """A business owned by the logged-in admin; payroll data is tenant-scoped."""
    resp = client.post("/api/entities/businesses", json={"legal_name": "Test Biz"})
    assert resp.status_code == 201
    return resp.get_json()["id"]


# --------------------------------------------------------------------------- #
# Calculator
# --------------------------------------------------------------------------- #


def test_calculate_hourly_payslip_without_deductions():
    employee = {
        "name": "Alice",
        "pay_type": "hourly",
        "rate": 20.0,
    }
    result = calculate_payslip(employee, regular_hours=40, overtime_hours=5)
    assert result["gross_pay"] == 950.0  # 40*20 + 5*30
    assert result["federal_tax"] == 37.31
    assert result["fica_tax"] == 58.9
    assert result["medicare_tax"] == 13.78
    assert result["net_pay"] == 840.01


def test_calculate_salary_payslip_biweekly():
    employee = {
        "name": "Bob",
        "pay_type": "salary",
        "rate": 52000.0,
        "pay_frequency": "biweekly",
        "state": "TX",
        "filing_status": "single",
    }
    result = calculate_payslip(employee)
    assert result["gross_pay"] == 2000.0  # 52000 / 26
    assert result["federal_tax"] == 161.6
    assert result["fica_tax"] == 124.0
    assert result["medicare_tax"] == 29.0
    assert result["net_pay"] == 1685.4


def test_calculate_salary_payslip_monthly():
    employee = {
        "name": "Carol",
        "pay_type": "salary",
        "rate": 60000.0,
        "pay_frequency": "monthly",
        "state": "TX",
        "filing_status": "single",
    }
    result = calculate_payslip(employee)
    assert result["gross_pay"] == 5000.0
    assert result["federal_tax"] == 430.12
    assert result["fica_tax"] == 310.0
    assert result["medicare_tax"] == 72.5
    assert result["net_pay"] == 4187.38


def test_calculate_payslip_with_deductions():
    employee = {
        "name": "Dave",
        "pay_type": "hourly",
        "rate": 25.0,
        "state": "TX",
        "filing_status": "single",
    }
    deductions = [
        {"name": "Health Insurance", "amount": 50.0, "category": "benefit"},
        {"name": "Gym", "amount": 25.0, "category": "other"},
    ]
    result = calculate_payslip(employee, regular_hours=40, deductions=deductions)
    assert result["gross_pay"] == 1000.0
    assert result["other_deductions"] == 75.0
    assert result["federal_tax"] == 42.31
    assert result["fica_tax"] == 62.0
    assert result["medicare_tax"] == 14.5
    assert result["net_pay"] == 806.19


def test_calculator_rejects_negative_hours():
    employee = {"name": "Eve", "pay_type": "hourly", "rate": 15.0}
    with pytest.raises(ValueError, match="negative"):
        calculate_payslip(employee, regular_hours=-1)


def test_calculator_rejects_invalid_employee():
    with pytest.raises(ValueError):
        calculate_payslip({"name": "", "pay_type": "hourly", "rate": 15.0})


# --------------------------------------------------------------------------- #
# Employee CRUD
# --------------------------------------------------------------------------- #


def test_create_and_list_employees(client, biz):
    resp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Alice", "pay_type": "hourly", "rate": 20.0},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Alice"
    assert body["pay_type"] == "hourly"
    assert body["rate"] == 20.0

    resp = client.get(f"/api/payroll/employees?business_id={biz}")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1


def test_get_employee_by_id(client, biz):
    resp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Bob", "pay_type": "salary", "rate": 52000.0, "pay_frequency": "biweekly"},
    )
    employee_id = resp.get_json()["id"]
    resp = client.get(f"/api/payroll/employees/{employee_id}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Bob"


def test_get_employee_not_found(client, biz):
    resp = client.get("/api/payroll/employees/999")
    assert resp.status_code == 404


def test_update_employee(client, biz):
    resp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Charlie", "pay_type": "hourly", "rate": 18.0},
    )
    employee_id = resp.get_json()["id"]
    resp = client.put(
        f"/api/payroll/employees/{employee_id}",
        json={"name": "Charles", "pay_type": "hourly", "rate": 20.0},
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Charles"
    assert resp.get_json()["rate"] == 20.0


def test_delete_employee(client, biz):
    resp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Dana", "pay_type": "hourly", "rate": 22.0},
    )
    employee_id = resp.get_json()["id"]
    resp = client.delete(f"/api/payroll/employees/{employee_id}")
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] is True
    resp = client.get(f"/api/payroll/employees/{employee_id}")
    assert resp.status_code == 404


def test_create_employee_validation_errors(client, biz):
    resp = client.post("/api/payroll/employees", json={"business_id": biz, })
    assert resp.status_code == 400
    resp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Test", "pay_type": "weekly", "rate": 10.0},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Pay period CRUD
# --------------------------------------------------------------------------- #


def test_create_and_list_pay_periods(client, biz):
    resp = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15", "pay_date": "2026-09-20"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["start_date"] == "2026-09-01"
    assert body["status"] == "open"


def test_pay_period_end_before_start(client, biz):
    resp = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-15", "end_date": "2026-09-01"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Payslips
# --------------------------------------------------------------------------- #


def test_create_payslip_hourly(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Eve", "pay_type": "hourly", "rate": 20.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    resp = client.post(
        "/api/payroll/payslips",
        json={
            "employee_id": emp["id"],
            "period_id": period["id"],
            "regular_hours": 40,
            "overtime_hours": 5,
            "deductions": [{"name": "Health", "amount": 50.0, "category": "benefit"}],
        },
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["gross_pay"] == 950.0
    assert body["other_deductions"] == 50.0
    assert body["federal_tax"] == 37.31
    assert body["fica_tax"] == 58.9
    assert body["medicare_tax"] == 13.78
    assert body["net_pay"] == 790.01
    assert len(body["deductions"]) == 1


def test_create_payslip_salary(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Frank", "pay_type": "salary", "rate": 52000.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    resp = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"]},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["gross_pay"] == 2000.0
    assert body["federal_tax"] == 161.6
    assert body["fica_tax"] == 124.0
    assert body["medicare_tax"] == 29.0
    assert body["net_pay"] == 1685.4


def test_duplicate_payslip_rejected(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Grace", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    payload = {"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 20}
    resp = client.post("/api/payroll/payslips", json=payload)
    assert resp.status_code == 201
    resp = client.post("/api/payroll/payslips", json=payload)
    assert resp.status_code == 400


def test_list_payslips_by_period(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Hank", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40},
    )
    resp = client.get(f"/api/payroll/payslips?period_id={period['id']}&business_id={biz}")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1


def test_update_payslip(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Ivy", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    payslip = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40},
    ).get_json()
    resp = client.put(
        f"/api/payroll/payslips/{payslip['id']}",
        json={"regular_hours": 45, "deductions": [{"name": "Tax", "amount": 10.0, "category": "tax"}]},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["gross_pay"] == 675.0
    assert body["deductions"][0]["name"] == "Tax"


def test_delete_payslip(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Jack", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    payslip = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40},
    ).get_json()
    resp = client.delete(f"/api/payroll/payslips/{payslip['id']}")
    assert resp.status_code == 200
    resp = client.get(f"/api/payroll/payslips/{payslip['id']}")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Assistant
# --------------------------------------------------------------------------- #


def test_assistant_local_command_list_employees(client, biz):
    client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Zoe", "pay_type": "hourly", "rate": 22.0},
    )
    resp = client.post("/api/payroll/assistant", json={"business_id": biz, "message": "list employees"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "Zoe" in body["response"]


def test_assistant_local_command_list_periods(client, biz):
    client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    )
    resp = client.post("/api/payroll/assistant", json={"business_id": biz, "message": "show pay periods"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "2026-09-01" in body["response"]


def test_assistant_asks_openexecutive_with_context(client, biz, monkeypatch):
    sse = (
        _sse_event({"type": "chunk", "content": "You have 1 employee.", "session_id": "sess-p"})
        + _sse_event({"type": "done", "session_id": "sess-p"})
    )
    fake = FakeOpenExecSession(MockResponse(text=sse, status_code=200))
    monkeypatch.setattr("payroll.openexec.http_session", fake)

    client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Leo", "pay_type": "salary", "rate": 52000.0},
    )
    resp = client.post(
        "/api/payroll/assistant",
        json={"business_id": biz, "message": "how many employees do I have?", "session_id": "sess-1"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "You have 1 employee."
    assert body["session_id"] == "sess-p"
    assert fake.calls["url"] == "http://openexec.test/chat"
    assert "Leo" in fake.calls["json"]["message"]
    assert fake.calls["json"]["session_id"] == "sess-1"
    assert fake.calls["headers"]["x-api-key"] == "test-key"


def test_assistant_openexecutive_error_returns_502(client, biz, monkeypatch):
    sse = _sse_event({"type": "error", "message": "model failure", "session_id": "sess-err"})
    fake = FakeOpenExecSession(MockResponse(text=sse, status_code=200))
    monkeypatch.setattr("payroll.openexec.http_session", fake)

    resp = client.post("/api/payroll/assistant", json={"business_id": biz, "message": "what is payroll?"})
    assert resp.status_code == 502
    assert "model failure" in resp.get_json()["error"]


def test_assistant_validation(client, biz):
    resp = client.post("/api/payroll/assistant", json={"business_id": biz, })
    assert resp.status_code == 400
    resp = client.post("/api/payroll/assistant", json={"business_id": biz, "message": "   "})
    assert resp.status_code == 400
    resp = client.post(
        "/api/payroll/assistant",
        json={"business_id": biz, "message": "hello", "committee_review": "false"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Reports
# --------------------------------------------------------------------------- #


def test_payroll_report_json(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Kate", "pay_type": "hourly", "rate": 30.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40},
    )

    resp = client.get(f"/api/payroll/reports/{period['id']}")
    assert resp.status_code == 200
    report = resp.get_json()
    assert report["total_employees"] == 1
    assert report["rows"][0]["employee_name"] == "Kate"
    assert report["rows"][0]["gross_pay"] == 1200.0
    assert report["total_gross"] == 1200.0
    assert report["total_net"] < report["total_gross"]


def test_payroll_report_csv(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Leo", "pay_type": "hourly", "rate": 25.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40},
    )

    resp = client.get(f"/api/payroll/reports/{period['id']}/csv")
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/csv")
    assert "attachment" in resp.headers["Content-Disposition"]
    csv_text = resp.data.decode("utf-8")
    assert "employee_name" in csv_text
    assert "Leo" in csv_text


def test_payroll_report_not_found(client, biz):
    resp = client.get("/api/payroll/reports/999")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# YTD and W-4 accuracy
# --------------------------------------------------------------------------- #


def _make_period(client, biz, start: str, end: str) -> dict:
    resp = client.post("/api/payroll/pay-periods", json={"business_id": biz, "start_date": start, "end_date": end})
    return resp.get_json()


def test_ytd_caps_social_security(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "High Earner", "pay_type": "salary", "rate": 400000.0, "pay_frequency": "biweekly"},
    ).get_json()

    base = datetime(2026, 1, 1)
    slips = []
    for i in range(12):
        start = (base + timedelta(days=14 * i)).strftime("%Y-%m-%d")
        end = (base + timedelta(days=14 * (i + 1) - 1)).strftime("%Y-%m-%d")
        period = _make_period(client, biz, start, end)
        slip = client.post(
            "/api/payroll/payslips",
            json={"employee_id": emp["id"], "period_id": period["id"]},
        ).get_json()
        slips.append(slip)

    assert slips[0]["fica_tax"] > 0
    # The last paycheck should hit the Social Security wage base cap.
    assert slips[-1]["fica_tax"] < slips[0]["fica_tax"]
    total_fica = sum(s["fica_tax"] for s in slips)
    expected_max = round(176100.0 * 0.062, 2)
    assert abs(total_fica - expected_max) < 0.1


def test_ytd_triggers_additional_medicare_tax(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Very High Earner", "pay_type": "salary", "rate": 500000.0, "pay_frequency": "biweekly"},
    ).get_json()

    base = datetime(2026, 1, 1)
    slips = []
    for i in range(12):
        start = (base + timedelta(days=14 * i)).strftime("%Y-%m-%d")
        end = (base + timedelta(days=14 * (i + 1) - 1)).strftime("%Y-%m-%d")
        period = _make_period(client, biz, start, end)
        slip = client.post(
            "/api/payroll/payslips",
            json={"employee_id": emp["id"], "period_id": period["id"]},
        ).get_json()
        slips.append(slip)

    base_medicare = slips[0]["medicare_tax"]
    # By the 11th paycheck the annual gross crosses the $200k threshold.
    assert slips[10]["medicare_tax"] > base_medicare
    assert slips[-1]["medicare_tax"] > slips[10]["medicare_tax"]


def test_w4_adjustments_reduce_federal_tax(client, biz):
    period_base = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-01-01", "end_date": "2026-01-31"},
    ).get_json()
    period_w4 = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-02-01", "end_date": "2026-02-28"},
    ).get_json()

    emp_base = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Base", "pay_type": "salary", "rate": 60000.0, "pay_frequency": "monthly"},
    ).get_json()
    base_slip = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp_base["id"], "period_id": period_base["id"]},
    ).get_json()

    emp_w4 = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, 
            "name": "W4",
            "pay_type": "salary",
            "rate": 60000.0,
            "pay_frequency": "monthly",
            "dependents": 2,
            "other_income": 5000.0,
            "w4_deductions": 5000.0,
        },
    ).get_json()
    w4_slip = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp_w4["id"], "period_id": period_w4["id"]},
    ).get_json()

    assert w4_slip["federal_tax"] < base_slip["federal_tax"]


def test_ytd_recalculated_on_payslip_update_and_delete(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "YTD Test", "pay_type": "hourly", "rate": 100.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-01-01", "end_date": "2026-01-14"},
    ).get_json()
    slip = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 10},
    ).get_json()

    # Update hours; YTD should reflect the new values.
    updated = client.put(
        f"/api/payroll/payslips/{slip['id']}",
        json={"regular_hours": 20},
    ).get_json()
    assert updated["gross_pay"] == 2000.0
    assert updated["fica_tax"] == round(2000.0 * 0.062, 2)

    # Delete the only payslip; YTD should go back to zero for the year.
    client.delete(f"/api/payroll/payslips/{slip['id']}")
    # A new payslip in the same year should compute taxes with zero YTD.
    period2 = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-01-15", "end_date": "2026-01-28"},
    ).get_json()
    slip2 = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period2["id"], "regular_hours": 10},
    ).get_json()
    assert slip2["fica_tax"] == round(1000.0 * 0.062, 2)


# --------------------------------------------------------------------------- #
# Review fixes: tax deductions, tax-year boundaries, ordering, validation
# --------------------------------------------------------------------------- #


def test_tax_deduction_reduces_net_pay(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Taxed", "pay_type": "hourly", "rate": 20.0},
    ).get_json()
    period = _make_period(client, biz, "2026-03-01", "2026-03-14")
    resp = client.post(
        "/api/payroll/payslips",
        json={
            "employee_id": emp["id"],
            "period_id": period["id"],
            "regular_hours": 40,
            "deductions": [{"name": "Local Tax", "amount": 25.0, "category": "tax"}],
        },
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["other_deductions"] == 25.0
    expected_net = (
        body["gross_pay"]
        - body["federal_tax"]
        - body["state_tax"]
        - body["fica_tax"]
        - body["medicare_tax"]
        - 25.0
    )
    assert abs(body["net_pay"] - expected_net) < 0.01


def test_december_period_paid_in_january_uses_pay_date_year(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "YearEnd", "pay_type": "hourly", "rate": 20.0},
    ).get_json()
    resp = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, 
            "start_date": "2026-12-20",
            "end_date": "2026-12-31",
            "pay_date": "2027-01-05",
        },
    )
    assert resp.status_code == 201
    period = resp.get_json()
    resp = client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40},
    )
    assert resp.status_code == 201

    import sqlite3

    db_path = client.application.config["PAYROLL_DATABASE"]
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT year FROM employee_ytd WHERE employee_id = ?", (emp["id"],)
        ).fetchall()
    finally:
        conn.close()
    years = sorted(r["year"] for r in rows)
    assert years == [2027]


def test_out_of_order_payslips_recompute_taxes(client, biz):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, 
            "name": "High Earner",
            "pay_type": "salary",
            "rate": 400000.0,
            "pay_frequency": "biweekly",
        },
    ).get_json()

    base = datetime(2026, 1, 1)
    periods = []
    for i in range(12):
        start = (base + timedelta(days=14 * i)).strftime("%Y-%m-%d")
        end = (base + timedelta(days=14 * (i + 1) - 1)).strftime("%Y-%m-%d")
        periods.append(_make_period(client, biz, start, end))

    for period in reversed(periods):
        resp = client.post(
            "/api/payroll/payslips",
            json={"employee_id": emp["id"], "period_id": period["id"]},
        )
        assert resp.status_code == 201

    slips = [
        client.get(f"/api/payroll/payslips?employee_id={emp['id']}&period_id={p['id']}&business_id={biz}").get_json()[0]
        for p in periods
    ]
    total_fica = sum(s["fica_tax"] for s in slips)
    expected_max = round(176100.0 * 0.062, 2)
    assert abs(total_fica - expected_max) < 0.1
    # The chronologically last paycheck should hit the Social Security cap.
    assert slips[-1]["fica_tax"] < slips[0]["fica_tax"]


@pytest.mark.parametrize("bad_date", ["2026-99-99", "2026-02-30", "2027-02-29"])
def test_invalid_calendar_dates_rejected(client, biz, bad_date):
    resp = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2026-01-01", "end_date": bad_date},
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_leap_day_accepted(client, biz):
    resp = client.post(
        "/api/payroll/pay-periods",
        json={"business_id": biz, "start_date": "2028-02-15", "end_date": "2028-02-29"},
    )
    assert resp.status_code == 201


@pytest.mark.parametrize("deductions", [[None], ["x"]])
def test_malformed_deduction_items_return_400(client, biz, deductions):
    emp = client.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Deductions", "pay_type": "hourly", "rate": 20.0},
    ).get_json()
    period = _make_period(client, biz, "2026-03-01", "2026-03-14")
    resp = client.post(
        "/api/payroll/payslips",
        json={
            "employee_id": emp["id"],
            "period_id": period["id"],
            "regular_hours": 40,
            "deductions": deductions,
        },
    )
    assert resp.status_code == 400
    assert "error" in resp.get_json()


# --------------------------------------------------------------------------- #
# Review fixes: roles and read-only viewers
# --------------------------------------------------------------------------- #


def test_register_cannot_self_assign_admin(app):
    anon = app.test_client()
    resp = anon.post(
        "/api/auth/register",
        json={"username": "admin", "password": "pw", "role": "admin"},
    )
    assert resp.status_code == 201  # bootstrap: first user may be admin

    resp = anon.post(
        "/api/auth/register",
        json={"username": "evil", "password": "pw", "role": "admin"},
    )
    assert resp.status_code == 403

    resp = anon.post("/api/auth/register", json={"username": "ok", "password": "pw"})
    assert resp.status_code == 201
    assert resp.get_json()["role"] == "viewer"


def test_viewer_cannot_mutate_payroll(app):
    admin = app.test_client()
    admin.post(
        "/api/auth/register",
        json={"username": "admin", "password": "pw", "role": "admin"},
    )
    admin.post("/api/auth/login", json={"username": "admin", "password": "pw"})
    resp = admin.post(
        "/api/auth/register",
        json={"username": "viewer", "password": "pw", "role": "viewer"},
    )
    assert resp.status_code == 201
    biz = admin.post(
        "/api/entities/businesses", json={"legal_name": "Biz"}
    ).get_json()["id"]
    resp = admin.post(
        f"/api/entities/businesses/{biz}/access",
        json={"user_id": 2, "role": "viewer"},
    )
    assert resp.status_code == 201

    viewer = app.test_client()
    viewer.post("/api/auth/login", json={"username": "viewer", "password": "pw"})

    assert viewer.get(f"/api/payroll/employees?business_id={biz}").status_code == 200
    resp = viewer.post(
        "/api/payroll/employees",
        json={"business_id": biz, "name": "Nope", "pay_type": "hourly", "rate": 10.0},
    )
    assert resp.status_code == 403

    resp = viewer.post("/api/payroll/assistant", json={"business_id": biz, "message": "list employees"})
    assert resp.status_code != 403


def test_cors_preflight_options_is_public(app):
    anon = app.test_client()
    resp = anon.options(
        "/api/payroll/employees/1",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "PUT",
        },
    )
    assert resp.status_code < 400
    allow_methods = resp.headers.get("Access-Control-Allow-Methods", "")
    assert "PUT" in allow_methods
