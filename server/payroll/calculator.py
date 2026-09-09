from __future__ import annotations

from typing import Any

from .tax import PERIODS_PER_YEAR, calculate_taxes


def _validate_employee(employee: dict[str, Any]) -> None:
    if not isinstance(employee, dict):
        raise ValueError("Invalid employee data")
    if not isinstance(employee.get("name"), str) or not employee["name"].strip():
        raise ValueError("Employee name is required")
    if employee.get("pay_type") not in {"hourly", "salary"}:
        raise ValueError("pay_type must be 'hourly' or 'salary'")
    if not isinstance(employee.get("rate"), (int, float)) or employee["rate"] <= 0:
        raise ValueError("rate must be a positive number")


def calculate_payslip(
    employee: dict[str, Any],
    regular_hours: float = 0.0,
    overtime_hours: float = 0.0,
    deductions: list[dict[str, Any]] | None = None,
    ytd: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Compute gross pay, tax withholdings, deductions and net pay."""
    _validate_employee(employee)

    regular = float(regular_hours)
    overtime = float(overtime_hours)
    if regular < 0 or overtime < 0:
        raise ValueError("Hours cannot be negative")

    rate = float(employee["rate"])
    pay_type = employee["pay_type"]

    if pay_type == "hourly":
        gross = round(regular * rate + overtime * rate * 1.5, 2)
        pay_frequency = employee.get("pay_frequency", employee.get("salary_frequency", "biweekly"))
    else:
        pay_frequency = employee.get("pay_frequency", employee.get("salary_frequency", "biweekly"))
        periods = PERIODS_PER_YEAR.get(pay_frequency, 26)
        gross = round(rate / periods, 2)

    deductions = deductions or []
    other_deductions = round(
        sum(float(d.get("amount", 0)) for d in deductions),
        2,
    )

    taxes = calculate_taxes(
        gross=gross,
        state=employee.get("state", ""),
        filing_status=employee.get("filing_status", "single"),
        pay_frequency=pay_frequency,
        federal_withholding=employee.get("federal_withholding", 0.0),
        other_income=employee.get("other_income", 0.0),
        w4_deductions=employee.get("w4_deductions", 0.0),
        dependents=employee.get("dependents", 0),
        multiple_jobs=bool(employee.get("multiple_jobs", False)),
        ytd=ytd,
    )

    total_deductions = round(
        taxes["federal_tax"]
        + taxes["state_tax"]
        + taxes["fica_tax"]
        + taxes["medicare_tax"]
        + other_deductions,
        2,
    )
    net_pay = round(gross - total_deductions, 2)

    return {
        "regular_hours": regular,
        "overtime_hours": overtime,
        "gross_pay": gross,
        "federal_tax": taxes["federal_tax"],
        "state_tax": taxes["state_tax"],
        "fica_tax": taxes["fica_tax"],
        "medicare_tax": taxes["medicare_tax"],
        "fica_wages": taxes["fica_wages"],
        "medicare_wages": taxes["medicare_wages"],
        "other_deductions": other_deductions,
        "net_pay": net_pay,
    }
