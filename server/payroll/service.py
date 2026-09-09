from __future__ import annotations

import datetime
import re
import sqlite3
from typing import Any

from .calculator import calculate_payslip
from .db import get_db, now_utc, row_to_dict

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

PAY_TYPES = {"hourly", "salary"}
PAY_FREQUENCIES = {"weekly", "biweekly", "semimonthly", "monthly", "annual"}
FILING_STATUSES = {"single", "married", "hoh"}
PERIOD_STATUSES = {"open", "closed"}
DEDUCTION_CATEGORIES = {"tax", "benefit", "garnishment", "other"}


def _validate_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required and must be a non-empty string")
    return name.strip()


def _validate_pay_type(pay_type: Any) -> str:
    if pay_type not in PAY_TYPES:
        raise ValueError("pay_type must be 'hourly' or 'salary'")
    return pay_type


def _validate_rate(rate: Any) -> float:
    try:
        value = float(rate)
    except (TypeError, ValueError):
        raise ValueError("rate must be a number")
    if value <= 0:
        raise ValueError("rate must be positive")
    return value


def _validate_date(date_str: Any, field: str = "date") -> str:
    if not isinstance(date_str, str) or not DATE_RE.match(date_str):
        raise ValueError(f"{field} must be a valid ISO date (YYYY-MM-DD)")
    try:
        parsed = datetime.date.fromisoformat(date_str)
    except ValueError:
        raise ValueError(f"{field} must be a valid ISO date (YYYY-MM-DD)")
    return parsed.isoformat()


def _validate_option(value: Any, allowed: set[str], field: str, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if value not in allowed:
        raise ValueError(f"{field} must be one of {sorted(allowed)}")
    return value


def _validate_non_negative(value: Any, field: str) -> float:
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if num < 0:
        raise ValueError(f"{field} cannot be negative")
    return num


def _validate_non_negative_int(value: Any, field: str) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be an integer")
    if num < 0:
        raise ValueError(f"{field} cannot be negative")
    return num


def _validate_bool(value: Any, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    if isinstance(value, int):
        return bool(value)
    raise ValueError(f"{field} must be a boolean")


def _employee_defaults(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": _validate_name(data.get("name")),
        "position": str(data.get("position", "")).strip(),
        "pay_type": _validate_pay_type(data.get("pay_type")),
        "pay_frequency": _validate_option(
            data.get("pay_frequency") or data.get("salary_frequency"),
            PAY_FREQUENCIES,
            "pay_frequency",
            "biweekly",
        ),
        "rate": _validate_rate(data.get("rate")),
        "state": str(data.get("state", "")).strip().upper()[:2],
        "filing_status": _validate_option(
            data.get("filing_status"), FILING_STATUSES, "filing_status", "single"
        ),
        "federal_withholding": _validate_non_negative(
            data.get("federal_withholding", 0), "federal_withholding"
        ),
        "dependents": _validate_non_negative_int(data.get("dependents", 0), "dependents"),
        "other_income": _validate_non_negative(data.get("other_income", 0), "other_income"),
        "w4_deductions": _validate_non_negative(data.get("w4_deductions", 0), "w4_deductions"),
        "multiple_jobs": _validate_bool(data.get("multiple_jobs", False), "multiple_jobs"),
    }


def _period_defaults(data: dict[str, Any]) -> dict[str, Any]:
    start_date = _validate_date(data.get("start_date"), "start_date")
    end_date = _validate_date(data.get("end_date"), "end_date")
    if end_date < start_date:
        raise ValueError("end_date cannot be before start_date")
    pay_date = data.get("pay_date")
    if pay_date is not None:
        pay_date = _validate_date(pay_date, "pay_date")
    return {
        "start_date": start_date,
        "end_date": end_date,
        "pay_date": pay_date,
        "status": _validate_option(data.get("status"), PERIOD_STATUSES, "status", "open"),
    }


def _deduction_defaults(data: dict[str, Any]) -> dict[str, Any]:
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("deduction name is required")
    return {
        "name": name.strip(),
        "amount": _validate_non_negative(data.get("amount"), "amount"),
        "category": _validate_option(
            data.get("category"), DEDUCTION_CATEGORIES, "category", "other"
        ),
    }


# --------------------------------------------------------------------------- #
# Employees
# --------------------------------------------------------------------------- #


def create_employee(data: dict[str, Any]) -> dict[str, Any]:
    fields = _employee_defaults(data)
    now = now_utc()
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO employees
                (name, position, pay_type, pay_frequency, rate, state, filing_status, federal_withholding, dependents, other_income, w4_deductions, multiple_jobs, created_at, updated_at)
            VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fields["name"],
                fields["position"],
                fields["pay_type"],
                fields["pay_frequency"],
                fields["rate"],
                fields["state"],
                fields["filing_status"],
                fields["federal_withholding"],
                fields["dependents"],
                fields["other_income"],
                fields["w4_deductions"],
                int(fields["multiple_jobs"]),
                now,
                now,
            ),
        )
        conn.commit()
        return get_employee(cursor.lastrowid)


def list_employees() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM employees ORDER BY created_at DESC").fetchall()
        return [row_to_dict(row) for row in rows]


def get_employee(employee_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
        return row_to_dict(row) if row else None


def update_employee(employee_id: int, data: dict[str, Any]) -> dict[str, Any]:
    if not get_employee(employee_id):
        raise ValueError("Employee not found")
    fields = _employee_defaults(data)
    now = now_utc()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE employees
            SET name = ?, position = ?, pay_type = ?, pay_frequency = ?,
                rate = ?, state = ?, filing_status = ?, federal_withholding = ?,
                dependents = ?, other_income = ?, w4_deductions = ?, multiple_jobs = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                fields["name"],
                fields["position"],
                fields["pay_type"],
                fields["pay_frequency"],
                fields["rate"],
                fields["state"],
                fields["filing_status"],
                fields["federal_withholding"],
                fields["dependents"],
                fields["other_income"],
                fields["w4_deductions"],
                int(fields["multiple_jobs"]),
                now,
                employee_id,
            ),
        )
        conn.commit()
        result = get_employee(employee_id)
        if result is None:
            raise ValueError("Employee not found")
        return result


def delete_employee(employee_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
        conn.commit()
        return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Pay periods
# --------------------------------------------------------------------------- #


def create_pay_period(data: dict[str, Any]) -> dict[str, Any]:
    fields = _period_defaults(data)
    now = now_utc()
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO pay_periods (start_date, end_date, pay_date, status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                fields["start_date"],
                fields["end_date"],
                fields["pay_date"],
                fields["status"],
                now,
            ),
        )
        conn.commit()
        return get_pay_period(cursor.lastrowid)


def list_pay_periods() -> list[dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM pay_periods ORDER BY start_date DESC").fetchall()
        return [row_to_dict(row) for row in rows]


def get_pay_period(period_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM pay_periods WHERE id = ?", (period_id,)).fetchone()
        return row_to_dict(row) if row else None


def update_pay_period(period_id: int, data: dict[str, Any]) -> dict[str, Any]:
    old_period = get_pay_period(period_id)
    if old_period is None:
        raise ValueError("Pay period not found")
    old_year = _payslip_year(old_period)
    fields = _period_defaults(data)
    new_year = _payslip_year(fields)
    now = now_utc()
    with get_db() as conn:
        conn.execute(
            """
            UPDATE pay_periods
            SET start_date = ?, end_date = ?, pay_date = ?, status = ?
            WHERE id = ?
            """,
            (
                fields["start_date"],
                fields["end_date"],
                fields["pay_date"],
                fields["status"],
                period_id,
            ),
        )
        # Moving a period can change which tax year its payslips belong to,
        # so recompute every affected employee for both the old and new year.
        employee_ids = [
            row["employee_id"]
            for row in conn.execute(
                "SELECT DISTINCT employee_id FROM payslips WHERE period_id = ?",
                (period_id,),
            ).fetchall()
        ]
        for employee_id in employee_ids:
            _recompute_employee_year(conn, employee_id, old_year)
            if new_year != old_year:
                _recompute_employee_year(conn, employee_id, new_year)
        conn.commit()
        result = _get_pay_period_conn(conn, period_id)
        if result is None:
            raise ValueError("Pay period not found")
        return result


def delete_pay_period(period_id: int) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM pay_periods WHERE id = ?", (period_id,))
        conn.commit()
        return cursor.rowcount > 0


# --------------------------------------------------------------------------- #
# Payslips
# --------------------------------------------------------------------------- #


def _serialize_payslip(row: Any, deductions: list[dict[str, Any]]) -> dict[str, Any]:
    data = row_to_dict(row)
    data["deductions"] = deductions
    return data


def _fetch_deductions(conn: Any, payslip_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM payslip_deductions WHERE payslip_id = ? ORDER BY id",
        (payslip_id,),
    ).fetchall()
    return [row_to_dict(row) for row in rows]


def _get_employee_conn(conn: Any, employee_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    return row_to_dict(row) if row else None


def _get_pay_period_conn(conn: Any, period_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM pay_periods WHERE id = ?", (period_id,)).fetchone()
    return row_to_dict(row) if row else None


def _effective_pay_date(period: dict[str, Any]) -> str:
    """The date that determines which tax year a period belongs to."""
    return period["pay_date"] or period["end_date"]


def _payslip_year(period: dict[str, Any]) -> int:
    return int(_effective_pay_date(period).split("-")[0])


def _get_employee_ytd_conn(conn: Any, employee_id: int, year: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM employee_ytd WHERE employee_id = ? AND year = ?",
        (employee_id, year),
    ).fetchone()
    if row is None:
        return {
            "gross_wages": 0.0,
            "fica_wages": 0.0,
            "medicare_wages": 0.0,
            "federal_tax": 0.0,
            "state_tax": 0.0,
            "fica_tax": 0.0,
            "medicare_tax": 0.0,
            "other_deductions": 0.0,
        }
    return row_to_dict(row)


def _recompute_employee_year(conn: Any, employee_id: int, year: int) -> None:
    """Recompute every payslip for an employee within a tax year.

    Payslips are recalculated in chronological pay order so year-to-date
    wage caps (Social Security, Additional Medicare) are applied correctly
    even when payslips were entered out of order.
    """
    employee = _get_employee_conn(conn, employee_id)
    if employee is None:
        return
    rows = conn.execute(
        """
        SELECT payslips.* FROM payslips
        JOIN pay_periods ON payslips.period_id = pay_periods.id
        WHERE payslips.employee_id = ?
          AND strftime('%Y', COALESCE(pay_periods.pay_date, pay_periods.end_date)) = ?
        ORDER BY COALESCE(pay_periods.pay_date, pay_periods.end_date),
                 pay_periods.id,
                 payslips.id
        """,
        (employee_id, str(year)),
    ).fetchall()

    ytd = {"fica_wages": 0.0, "medicare_wages": 0.0}
    now = now_utc()
    for slip in rows:
        calc = calculate_payslip(
            employee,
            slip["regular_hours"],
            slip["overtime_hours"],
            _fetch_deductions(conn, slip["id"]),
            ytd,
        )
        conn.execute(
            """
            UPDATE payslips
            SET gross_pay = ?, federal_tax = ?, state_tax = ?, fica_tax = ?,
                medicare_tax = ?, fica_wages = ?, medicare_wages = ?,
                other_deductions = ?, net_pay = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                calc["gross_pay"],
                calc["federal_tax"],
                calc["state_tax"],
                calc["fica_tax"],
                calc["medicare_tax"],
                calc["fica_wages"],
                calc["medicare_wages"],
                calc["other_deductions"],
                calc["net_pay"],
                now,
                slip["id"],
            ),
        )
        ytd["fica_wages"] += calc["fica_wages"]
        ytd["medicare_wages"] += calc["medicare_wages"]

    _recalculate_employee_ytd(conn, employee_id, year)


def _recalculate_employee_ytd(conn: Any, employee_id: int, year: int) -> None:
    """Recompute an employee's YTD for a year from all stored payslips.

    This is called after any payslip mutation so YTD always matches actual data.
    """
    conn.execute("DELETE FROM employee_ytd WHERE employee_id = ? AND year = ?", (employee_id, year))
    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(gross_pay), 0) as gross_wages,
            COALESCE(SUM(federal_tax), 0) as federal_tax,
            COALESCE(SUM(state_tax), 0) as state_tax,
            COALESCE(SUM(fica_tax), 0) as fica_tax,
            COALESCE(SUM(medicare_tax), 0) as medicare_tax,
            COALESCE(SUM(other_deductions), 0) as other_deductions,
            COALESCE(SUM(fica_wages), 0) as fica_wages,
            COALESCE(SUM(medicare_wages), 0) as medicare_wages
        FROM payslips
        JOIN pay_periods ON payslips.period_id = pay_periods.id
        WHERE payslips.employee_id = ? AND strftime('%Y', COALESCE(pay_periods.pay_date, pay_periods.end_date)) = ?
        """,
        (employee_id, str(year)),
    ).fetchone()

    now = now_utc()
    conn.execute(
        """
        INSERT INTO employee_ytd
            (employee_id, year, gross_wages, federal_tax, state_tax, fica_tax,
             medicare_tax, other_deductions, fica_wages, medicare_wages, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            employee_id,
            year,
            row["gross_wages"],
            row["federal_tax"],
            row["state_tax"],
            row["fica_tax"],
            row["medicare_tax"],
            row["other_deductions"],
            row["fica_wages"],
            row["medicare_wages"],
            now,
            now,
        ),
    )


def _build_payslip_values(
    employee: dict[str, Any], data: dict[str, Any], ytd: dict[str, Any] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    regular_hours = _validate_non_negative(data.get("regular_hours", 0), "regular_hours")
    overtime_hours = _validate_non_negative(data.get("overtime_hours", 0), "overtime_hours")
    raw_deductions = data.get("deductions", [])
    if not isinstance(raw_deductions, list):
        raise ValueError("deductions must be a list")
    deductions = []
    for d in raw_deductions:
        if not isinstance(d, dict):
            raise ValueError("each deduction must be an object")
        deductions.append(_deduction_defaults(d))
    calc = calculate_payslip(employee, regular_hours, overtime_hours, deductions, ytd)
    return calc, deductions


def create_payslip(employee_id: int, period_id: int, data: dict[str, Any]) -> dict[str, Any]:
    now = now_utc()

    with get_db() as conn:
        employee = _get_employee_conn(conn, employee_id)
        if employee is None:
            raise ValueError("Employee not found")
        period = _get_pay_period_conn(conn, period_id)
        if period is None:
            raise ValueError("Pay period not found")

        year = _payslip_year(period)
        calc, deductions = _build_payslip_values(employee, data)

        try:
            cursor = conn.execute(
                """
                INSERT INTO payslips
                    (employee_id, period_id, regular_hours, overtime_hours, gross_pay, federal_tax,
                     state_tax, fica_tax, medicare_tax, fica_wages, medicare_wages,
                     other_deductions, net_pay, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    period_id,
                    calc["regular_hours"],
                    calc["overtime_hours"],
                    calc["gross_pay"],
                    calc["federal_tax"],
                    calc["state_tax"],
                    calc["fica_tax"],
                    calc["medicare_tax"],
                    calc["fica_wages"],
                    calc["medicare_wages"],
                    calc["other_deductions"],
                    calc["net_pay"],
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("A payslip already exists for this employee and period") from exc
        payslip_id = cursor.lastrowid
        for deduction in deductions:
            conn.execute(
                """
                INSERT INTO payslip_deductions (payslip_id, name, amount, category, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (payslip_id, deduction["name"], deduction["amount"], deduction["category"], now),
            )
        _recompute_employee_year(conn, employee_id, year)
        conn.commit()
        return _get_payslip_with_deductions(conn, payslip_id)


def _get_payslip_with_deductions(conn: Any, payslip_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM payslips WHERE id = ?", (payslip_id,)).fetchone()
    if row is None:
        raise ValueError("Payslip not found")
    deductions = _fetch_deductions(conn, payslip_id)
    return _serialize_payslip(row, deductions)


def get_payslip(payslip_id: int) -> dict[str, Any] | None:
    with get_db() as conn:
        try:
            return _get_payslip_with_deductions(conn, payslip_id)
        except ValueError:
            return None


def list_payslips(employee_id: int | None = None, period_id: int | None = None) -> list[dict[str, Any]]:
    query = "SELECT * FROM payslips WHERE 1=1"
    params: list[Any] = []
    if employee_id is not None:
        query += " AND employee_id = ?"
        params.append(employee_id)
    if period_id is not None:
        query += " AND period_id = ?"
        params.append(period_id)
    query += " ORDER BY created_at DESC"
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_get_payslip_with_deductions(conn, row["id"]) for row in rows]


def update_payslip(payslip_id: int, data: dict[str, Any]) -> dict[str, Any]:
    now = now_utc()

    with get_db() as conn:
        row = conn.execute("SELECT * FROM payslips WHERE id = ?", (payslip_id,)).fetchone()
        if row is None:
            raise ValueError("Payslip not found")
        employee = _get_employee_conn(conn, row["employee_id"])
        if employee is None:
            raise ValueError("Employee not found")
        period = _get_pay_period_conn(conn, row["period_id"])
        if period is None:
            raise ValueError("Pay period not found")

        year = _payslip_year(period)
        calc, deductions = _build_payslip_values(employee, data)

        conn.execute(
            """
            UPDATE payslips
            SET regular_hours = ?, overtime_hours = ?, gross_pay = ?, federal_tax = ?,
                state_tax = ?, fica_tax = ?, medicare_tax = ?, fica_wages = ?, medicare_wages = ?,
                other_deductions = ?, net_pay = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                calc["regular_hours"],
                calc["overtime_hours"],
                calc["gross_pay"],
                calc["federal_tax"],
                calc["state_tax"],
                calc["fica_tax"],
                calc["medicare_tax"],
                calc["fica_wages"],
                calc["medicare_wages"],
                calc["other_deductions"],
                calc["net_pay"],
                now,
                payslip_id,
            ),
        )
        conn.execute("DELETE FROM payslip_deductions WHERE payslip_id = ?", (payslip_id,))
        for deduction in deductions:
            conn.execute(
                """
                INSERT INTO payslip_deductions (payslip_id, name, amount, category, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (payslip_id, deduction["name"], deduction["amount"], deduction["category"], now),
            )
        _recompute_employee_year(conn, row["employee_id"], year)
        conn.commit()
        return _get_payslip_with_deductions(conn, payslip_id)


def delete_payslip(payslip_id: int) -> bool:
    with get_db() as conn:
        row = conn.execute(
            "SELECT employee_id, period_id FROM payslips WHERE id = ?", (payslip_id,)
        ).fetchone()
        if row is None:
            return False
        period = _get_pay_period_conn(conn, row["period_id"])
        if period is None:
            return False
        year = _payslip_year(period)

        cursor = conn.execute("DELETE FROM payslips WHERE id = ?", (payslip_id,))
        _recompute_employee_year(conn, row["employee_id"], year)
        conn.commit()
        return cursor.rowcount > 0


def get_payroll_report(period_id: int) -> dict[str, Any]:
    period = get_pay_period(period_id)
    if period is None:
        raise ValueError("Pay period not found")

    employees_by_id = {emp["id"]: emp for emp in list_employees()}
    payslips = list_payslips(period_id=period_id)

    rows: list[dict[str, Any]] = []
    for slip in payslips:
        employee = employees_by_id.get(slip["employee_id"], {})
        rows.append(
            {
                "employee_id": slip["employee_id"],
                "employee_name": employee.get("name", f"Employee #{slip['employee_id']}"),
                "position": employee.get("position", ""),
                "pay_type": employee.get("pay_type", ""),
                "period_start": period["start_date"],
                "period_end": period["end_date"],
                "regular_hours": slip["regular_hours"],
                "overtime_hours": slip["overtime_hours"],
                "gross_pay": slip["gross_pay"],
                "federal_tax": slip["federal_tax"],
                "state_tax": slip["state_tax"],
                "fica_tax": slip["fica_tax"],
                "medicare_tax": slip["medicare_tax"],
                "other_deductions": slip["other_deductions"],
                "net_pay": slip["net_pay"],
            }
        )

    return {
        "period": period,
        "rows": rows,
        "total_employees": len(rows),
        "total_gross": round(sum(r["gross_pay"] for r in rows), 2),
        "total_net": round(sum(r["net_pay"] for r in rows), 2),
        "total_taxes": round(
            sum(r["federal_tax"] + r["state_tax"] + r["fica_tax"] + r["medicare_tax"] for r in rows), 2
        ),
    }
