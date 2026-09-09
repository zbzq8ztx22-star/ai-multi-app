from __future__ import annotations

from typing import Any

# Approximate 2025 U.S. federal tax parameters. These are not legal advice and
# should be replaced with official IRS values for production use.
FEDERAL_STANDARD_DEDUCTIONS: dict[str, float] = {
    "single": 15000.0,
    "married": 30000.0,
    "hoh": 22500.0,
}

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
) -> float:
    """Return per-paycheck federal income tax withholding."""
    status = filing_status if filing_status in FEDERAL_STANDARD_DEDUCTIONS else "single"
    standard_deduction = FEDERAL_STANDARD_DEDUCTIONS[status]
    brackets = FEDERAL_BRACKETS[status]
    taxable = max(0.0, annual_gross - standard_deduction)
    annual_tax = _bracket_tax(taxable, brackets)
    return round(annual_tax / periods + float(extra_withholding), 2)


def fica_tax(gross: float, annual_gross: float) -> float:
    """Return Social Security tax for this paycheck.

    The calculation caps the taxable portion of the paycheck based on the
    annualized gross and the Social Security wage base.
    """
    ytd_before_period = annual_gross - gross
    remaining_taxable = max(0.0, SOCIAL_SECURITY_WAGE_BASE - ytd_before_period)
    taxable_wages = min(gross, remaining_taxable)
    return round(taxable_wages * SOCIAL_SECURITY_RATE, 2)


def medicare_tax(gross: float, annual_gross: float, filing_status: str = "single") -> float:
    """Return Medicare tax for this paycheck, including Additional Medicare Tax."""
    base = gross * MEDICARE_RATE
    threshold = MEDICARE_ADDITIONAL_THRESHOLD.get(filing_status, 200000.0)
    # Annual additional tax is spread evenly across pay periods.
    additional_annual = max(0.0, annual_gross - threshold) * MEDICARE_ADDITIONAL_RATE
    periods = PERIODS_PER_YEAR.get("biweekly", 26)  # fallback
    additional = round(additional_annual / periods, 2)
    return round(base + additional, 2)


def state_income_tax(
    gross: float,
    state: str,
    filing_status: str = "single",
    periods: int = 26,
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
    annual_gross = gross * periods
    taxable = max(0.0, annual_gross - standard)
    return round(taxable * rate / periods, 2)


def calculate_taxes(
    gross: float,
    state: str,
    filing_status: str,
    pay_frequency: str,
    federal_withholding: float = 0.0,
) -> dict[str, float]:
    """Compute all tax withholdings for a single paycheck."""
    periods = PERIODS_PER_YEAR.get(pay_frequency, 26)
    annual_gross = gross * periods
    federal = federal_income_tax(annual_gross, filing_status, federal_withholding, periods)
    fica = fica_tax(gross, annual_gross)
    medicare = medicare_tax(gross, annual_gross, filing_status)
    state = state_income_tax(gross, state, filing_status, periods)
    return {
        "federal_tax": federal,
        "state_tax": state,
        "fica_tax": fica,
        "medicare_tax": medicare,
    }
