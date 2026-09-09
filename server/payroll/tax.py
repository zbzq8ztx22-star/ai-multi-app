from __future__ import annotations

from typing import Any

# Approximate 2025 U.S. federal tax parameters. These are not legal advice and
# should be replaced with official IRS values for production use.
FEDERAL_STANDARD_DEDUCTIONS: dict[str, float] = {
    "single": 15000.0,
    "married": 30000.0,
    "hoh": 22500.0,
}

# Reduced standard deduction for employees who check the W-4 Step 2(c) box
# because they hold multiple jobs (2025 approximate values).
W4_REDUCED_STANDARD_DEDUCTIONS: dict[str, float] = {
    "single": 8600.0,
    "married": 16600.0,
    "hoh": 12950.0,
}

# Simplified per-dependent tax credit. The actual Child Tax Credit is $2,000
# for qualifying children and $500 for other dependents.
DEPENDENT_TAX_CREDIT = 500.0

# Brackets are (lower, upper, rate). Upper of None means no upper bound.
FEDERAL_BRACKETS: dict[str, list[tuple[float, float | None, float]]] = {
    "single": [
        (0.0, 11925.0, 0.10),
        (11925.0, 48475.0, 0.12),
        (48475.0, 103350.0, 0.22),
        (103350.0, 197300.0, 0.24),
        (197300.0, 250525.0, 0.32),
        (250525.0, 626350.0, 0.35),
        (626350.0, None, 0.37),
    ],
    "married": [
        (0.0, 23850.0, 0.10),
        (23850.0, 96950.0, 0.12),
        (96950.0, 206700.0, 0.22),
        (206700.0, 364850.0, 0.24),
        (364850.0, 462500.0, 0.32),
        (462500.0, 693750.0, 0.35),
        (693750.0, None, 0.37),
    ],
    "hoh": [
        (0.0, 17000.0, 0.10),
        (17000.0, 64850.0, 0.12),
        (64850.0, 103350.0, 0.22),
        (103350.0, 197300.0, 0.24),
        (197300.0, 250500.0, 0.32),
        (250500.0, 626350.0, 0.35),
        (626350.0, None, 0.37),
    ],
}

SOCIAL_SECURITY_RATE = 0.062
SOCIAL_SECURITY_WAGE_BASE = 176100.0

MEDICARE_RATE = 0.0145
MEDICARE_ADDITIONAL_RATE = 0.009
MEDICARE_ADDITIONAL_THRESHOLD: dict[str, float] = {
    "single": 200000.0,
    "married": 250000.0,
    "hoh": 200000.0,
}

# Approximate state income tax tables. Flat rates are used as placeholders;
# progressive states should provide bracket data in the same shape.
STATE_TAX_TABLES: dict[str, dict[str, Any]] = {
    "CA": {"type": "flat", "rate": 0.06, "standard_deduction": 0.0},
    "NY": {"type": "flat", "rate": 0.055, "standard_deduction": 0.0},
    "TX": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "FL": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "IL": {"type": "flat", "rate": 0.0495, "standard_deduction": 0.0},
    "PA": {"type": "flat", "rate": 0.0307, "standard_deduction": 0.0},
    "NJ": {"type": "flat", "rate": 0.05, "standard_deduction": 0.0},
    "OH": {"type": "flat", "rate": 0.0399, "standard_deduction": 0.0},
    "VA": {"type": "flat", "rate": 0.0575, "standard_deduction": 0.0},
    "WA": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "NV": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "TN": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "WY": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "SD": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "AK": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
    "NH": {"type": "flat", "rate": 0.0, "standard_deduction": 0.0},
}

PERIODS_PER_YEAR = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
    "annual": 1,
}


def _bracket_tax(taxable_income: float, brackets: list[tuple[float, float | None, float]]) -> float:
    tax = 0.0
    for lower, upper, rate in brackets:
        if taxable_income <= lower:
            break
        bracket_top = upper if upper is not None else taxable_income
        taxable_in_bracket = min(taxable_income, bracket_top) - lower
        if taxable_in_bracket > 0:
            tax += taxable_in_bracket * rate
    return round(tax, 2)


def federal_income_tax(
    annual_gross: float,
    filing_status: str = "single",
    extra_withholding: float = 0.0,
    periods: int = 26,
    other_income: float = 0.0,
    w4_deductions: float = 0.0,
    dependents: int = 0,
    multiple_jobs: bool = False,
) -> float:
    """Return per-paycheck federal income tax withholding.

    Supports simplified W-4 adjustments: other income, deductions, dependents
    and the multiple-jobs checkbox.
    """
    status = filing_status if filing_status in FEDERAL_STANDARD_DEDUCTIONS else "single"
    standard_deductions = W4_REDUCED_STANDARD_DEDUCTIONS if multiple_jobs else FEDERAL_STANDARD_DEDUCTIONS
    standard_deduction = standard_deductions[status]
    brackets = FEDERAL_BRACKETS[status]

    total_income = annual_gross + float(other_income)
    taxable = max(0.0, total_income - standard_deduction - float(w4_deductions))
    annual_tax = _bracket_tax(taxable, brackets)

    # Simplified dependent credit.
    annual_tax = max(0.0, annual_tax - int(dependents) * DEPENDENT_TAX_CREDIT)

    return round(annual_tax / periods + float(extra_withholding), 2)


def fica_tax(gross: float, ytd_fica_wages: float = 0.0) -> tuple[float, float]:
    """Return Social Security tax and the taxable wages for this paycheck.

    The taxable wages are capped by the Social Security wage base.
    """
    remaining = max(0.0, SOCIAL_SECURITY_WAGE_BASE - float(ytd_fica_wages))
    taxable_wages = min(float(gross), remaining)
    tax = round(taxable_wages * SOCIAL_SECURITY_RATE, 2)
    return tax, taxable_wages


def medicare_tax(
    gross: float,
    ytd_medicare_wages: float = 0.0,
    filing_status: str = "single",
) -> tuple[float, float]:
    """Return Medicare tax and the Medicare wages for this paycheck.

    The regular Medicare rate applies to all wages. Additional Medicare Tax
    (0.9%) applies incrementally once YTD Medicare wages exceed the threshold.
    """
    gross = float(gross)
    base = round(gross * MEDICARE_RATE, 2)
    threshold = MEDICARE_ADDITIONAL_THRESHOLD.get(filing_status, 200000.0)

    wages_before = float(ytd_medicare_wages)
    wages_after = wages_before + gross
    additional_taxable = max(0.0, wages_after - threshold) - max(0.0, wages_before - threshold)
    additional = round(additional_taxable * MEDICARE_ADDITIONAL_RATE, 2)

    return round(base + additional, 2), gross


def state_income_tax(
    gross: float,
    state: str,
    filing_status: str = "single",
    periods: int = 26,
    other_income: float = 0.0,
    w4_deductions: float = 0.0,
) -> float:
    """Return per-paycheck state income tax withholding.

    Uses the tables in STATE_TAX_TABLES. States not listed are assumed to
    have no income tax in this simplified model.
    """
    if not state:
        return 0.0
    state = state.upper()
    table = STATE_TAX_TABLES.get(state)
    if table is None or table.get("type") != "flat":
        return 0.0

    rate = float(table.get("rate", 0.0))
    standard = float(table.get("standard_deduction", 0.0))
    annual_gross = float(gross) * periods + float(other_income)
    taxable = max(0.0, annual_gross - standard - float(w4_deductions))
    return round(taxable * rate / periods, 2)


def calculate_taxes(
    gross: float,
    state: str,
    filing_status: str,
    pay_frequency: str,
    federal_withholding: float = 0.0,
    other_income: float = 0.0,
    w4_deductions: float = 0.0,
    dependents: int = 0,
    multiple_jobs: bool = False,
    ytd: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Compute all tax withholdings and taxable wages for a single paycheck.

    ``ytd`` should contain ``fica_wages`` and ``medicare_wages`` prior to the
    current paycheck. Missing keys are treated as zero.
    """
    periods = PERIODS_PER_YEAR.get(pay_frequency, 26)
    annual_gross = float(gross) * periods

    federal = federal_income_tax(
        annual_gross,
        filing_status,
        federal_withholding,
        periods,
        other_income,
        w4_deductions,
        dependents,
        multiple_jobs,
    )
    fica, fica_wages = fica_tax(gross, ytd.get("fica_wages", 0.0) if ytd else 0.0)
    medicare, medicare_wages = medicare_tax(
        gross,
        ytd.get("medicare_wages", 0.0) if ytd else 0.0,
        filing_status,
    )
    state_tax = state_income_tax(
        gross,
        state,
        filing_status,
        periods,
        other_income,
        w4_deductions,
    )

    return {
        "federal_tax": federal,
        "state_tax": state_tax,
        "fica_tax": fica,
        "medicare_tax": medicare,
        "fica_wages": fica_wages,
        "medicare_wages": medicare_wages,
    }
