from __future__ import annotations

from typing import Any

RULES = {
    2025: {
        "source": "https://www.irs.gov/instructions/i1040gi",
        "standard_deductions": {
            "single": 15750.0,
            "married_joint": 31500.0,
            "married_separate": 15750.0,
            "hoh": 23625.0,
            "widow": 31500.0,
        },
        "brackets": {
            "single": [(11925, .10), (48475, .12), (103350, .22), (197300, .24), (250525, .32), (626350, .35), (None, .37)],
            "married_joint": [(23850, .10), (96950, .12), (206700, .22), (394600, .24), (501050, .32), (751600, .35), (None, .37)],
            "married_separate": [(11925, .10), (48475, .12), (103350, .22), (197300, .24), (250525, .32), (375800, .35), (None, .37)],
            "hoh": [(17000, .10), (64850, .12), (103350, .22), (197300, .24), (250500, .32), (626350, .35), (None, .37)],
            "widow": [(23850, .10), (96950, .12), (206700, .22), (394600, .24), (501050, .32), (751600, .35), (None, .37)],
        },
    }
}

AMOUNT_FIELDS = (
    "wages", "interest_income", "dividend_income", "business_income", "capital_gains",
    "other_income", "adjustments", "itemized_deductions", "credits", "federal_withholding",
    "estimated_payments", "state_tax_liability", "state_withholding",
)


def _progressive_tax(income: float, brackets: list[tuple[float | None, float]]) -> float:
    tax = 0.0
    lower = 0.0
    for upper, rate in brackets:
        top = income if upper is None else min(income, upper)
        if top > lower:
            tax += (top - lower) * rate
        if upper is None or income <= upper:
            break
        lower = upper
    return round(tax, 2)


def calculate_personal_return(data: dict[str, Any]) -> dict[str, float]:
    year = int(data.get("tax_year", 0))
    if year not in RULES:
        raise ValueError("Tax year is not supported")
    filing_status = data.get("filing_status", "single")
    rules = RULES[year]
    if filing_status not in rules["brackets"]:
        raise ValueError("Invalid filing_status")
    amounts = {}
    for field in AMOUNT_FIELDS:
        try:
            amounts[field] = float(data.get(field, 0) or 0)
        except (TypeError, ValueError):
            raise ValueError(f"{field} must be a number")
        if amounts[field] < 0:
            raise ValueError(f"{field} cannot be negative")
    total_income = sum(amounts[field] for field in ("wages", "interest_income", "dividend_income", "business_income", "capital_gains", "other_income"))
    agi = max(0.0, total_income - amounts["adjustments"])
    deduction = max(rules["standard_deductions"][filing_status], amounts["itemized_deductions"])
    taxable_income = max(0.0, agi - deduction)
    federal_tax = max(0.0, _progressive_tax(taxable_income, rules["brackets"][filing_status]) - amounts["credits"])
    federal_payments = amounts["federal_withholding"] + amounts["estimated_payments"]
    return {
        "total_income": round(total_income, 2),
        "adjusted_gross_income": round(agi, 2),
        "deduction": round(deduction, 2),
        "taxable_income": round(taxable_income, 2),
        "federal_tax": round(federal_tax, 2),
        "federal_refund_or_due": round(federal_payments - federal_tax, 2),
        "state_refund_or_due": round(amounts["state_withholding"] - amounts["state_tax_liability"], 2),
    }
