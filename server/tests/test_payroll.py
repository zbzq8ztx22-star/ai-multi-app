from __future__ import annotations

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


def test_create_and_list_employees(client):
    resp = client.post(
        "/api/payroll/employees",
        json={"name": "Alice", "pay_type": "hourly", "rate": 20.0},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["name"] == "Alice"
    assert body["pay_type"] == "hourly"
    assert body["rate"] == 20.0

    resp = client.get("/api/payroll/employees")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1


def test_get_employee_by_id(client):
    resp = client.post(
        "/api/payroll/employees",
        json={"name": "Bob", "pay_type": "salary", "rate": 52000.0, "pay_frequency": "biweekly"},
    )
    employee_id = resp.get_json()["id"]
    resp = client.get(f"/api/payroll/employees/{employee_id}")
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Bob"


def test_get_employee_not_found(client):
    resp = client.get("/api/payroll/employees/999")
    assert resp.status_code == 404


def test_update_employee(client):
    resp = client.post(
        "/api/payroll/employees",
        json={"name": "Charlie", "pay_type": "hourly", "rate": 18.0},
    )
    employee_id = resp.get_json()["id"]
    resp = client.put(
        f"/api/payroll/employees/{employee_id}",
        json={"name": "Charles", "pay_type": "hourly", "rate": 20.0},
    )
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Charles"
    assert resp.get_json()["rate"] == 20.0


def test_delete_employee(client):
    resp = client.post(
        "/api/payroll/employees",
        json={"name": "Dana", "pay_type": "hourly", "rate": 22.0},
    )
    employee_id = resp.get_json()["id"]
    resp = client.delete(f"/api/payroll/employees/{employee_id}")
    assert resp.status_code == 200
    assert resp.get_json()["deleted"] is True
    resp = client.get(f"/api/payroll/employees/{employee_id}")
    assert resp.status_code == 404


def test_create_employee_validation_errors(client):
    resp = client.post("/api/payroll/employees", json={})
    assert resp.status_code == 400
    resp = client.post(
        "/api/payroll/employees",
        json={"name": "Test", "pay_type": "weekly", "rate": 10.0},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Pay period CRUD
# --------------------------------------------------------------------------- #


def test_create_and_list_pay_periods(client):
    resp = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15", "pay_date": "2026-09-20"},
    )
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["start_date"] == "2026-09-01"
    assert body["status"] == "open"


def test_pay_period_end_before_start(client):
    resp = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-15", "end_date": "2026-09-01"},
    )
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# Payslips
# --------------------------------------------------------------------------- #


def test_create_payslip_hourly(client):
    emp = client.post(
        "/api/payroll/employees",
        json={"name": "Eve", "pay_type": "hourly", "rate": 20.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15"},
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


def test_create_payslip_salary(client):
    emp = client.post(
        "/api/payroll/employees",
        json={"name": "Frank", "pay_type": "salary", "rate": 52000.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15"},
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


def test_duplicate_payslip_rejected(client):
    emp = client.post(
        "/api/payroll/employees",
        json={"name": "Grace", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    payload = {"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 20}
    resp = client.post("/api/payroll/payslips", json=payload)
    assert resp.status_code == 201
    resp = client.post("/api/payroll/payslips", json=payload)
    assert resp.status_code == 400


def test_list_payslips_by_period(client):
    emp = client.post(
        "/api/payroll/employees",
        json={"name": "Hank", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15"},
    ).get_json()
    client.post(
        "/api/payroll/payslips",
        json={"employee_id": emp["id"], "period_id": period["id"], "regular_hours": 40},
    )
    resp = client.get(f"/api/payroll/payslips?period_id={period['id']}")
    assert resp.status_code == 200
    assert len(resp.get_json()) == 1


def test_update_payslip(client):
    emp = client.post(
        "/api/payroll/employees",
        json={"name": "Ivy", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15"},
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


def test_delete_payslip(client):
    emp = client.post(
        "/api/payroll/employees",
        json={"name": "Jack", "pay_type": "hourly", "rate": 15.0},
    ).get_json()
    period = client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15"},
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


def test_assistant_local_command_list_employees(client):
    client.post(
        "/api/payroll/employees",
        json={"name": "Zoe", "pay_type": "hourly", "rate": 22.0},
    )
    resp = client.post("/api/payroll/assistant", json={"message": "list employees"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "Zoe" in body["response"]


def test_assistant_local_command_list_periods(client):
    client.post(
        "/api/payroll/pay-periods",
        json={"start_date": "2026-09-01", "end_date": "2026-09-15"},
    )
    resp = client.post("/api/payroll/assistant", json={"message": "show pay periods"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "2026-09-01" in body["response"]


def test_assistant_asks_openexecutive_with_context(client, monkeypatch):
    sse = (
        _sse_event({"type": "chunk", "content": "You have 1 employee.", "session_id": "sess-p"})
        + _sse_event({"type": "done", "session_id": "sess-p"})
    )
    fake = FakeOpenExecSession(MockResponse(text=sse, status_code=200))
    monkeypatch.setattr("payroll.openexec.http_session", fake)

    client.post(
        "/api/payroll/employees",
        json={"name": "Leo", "pay_type": "salary", "rate": 52000.0},
    )
    resp = client.post(
        "/api/payroll/assistant",
        json={"message": "how many employees do I have?", "session_id": "sess-1"},
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response"] == "You have 1 employee."
    assert body["session_id"] == "sess-p"
    assert fake.calls["url"] == "http://openexec.test/chat"
    assert "Leo" in fake.calls["json"]["message"]
    assert fake.calls["json"]["session_id"] == "sess-1"
    assert fake.calls["headers"]["x-api-key"] == "test-key"


def test_assistant_openexecutive_error_returns_502(client, monkeypatch):
    sse = _sse_event({"type": "error", "message": "model failure", "session_id": "sess-err"})
    fake = FakeOpenExecSession(MockResponse(text=sse, status_code=200))
    monkeypatch.setattr("payroll.openexec.http_session", fake)

    resp = client.post("/api/payroll/assistant", json={"message": "what is payroll?"})
    assert resp.status_code == 502
    assert "model failure" in resp.get_json()["error"]


def test_assistant_validation(client):
    resp = client.post("/api/payroll/assistant", json={})
    assert resp.status_code == 400
    resp = client.post("/api/payroll/assistant", json={"message": "   "})
    assert resp.status_code == 400
    resp = client.post(
        "/api/payroll/assistant",
        json={"message": "hello", "committee_review": "false"},
    )
    assert resp.status_code == 400
