from __future__ import annotations

from typing import Any

from payroll.db import get_db, row_to_dict


def overview() -> dict[str, Any]:
    """Aggregate high-level counts and recent activity across modules.

    All counts are read-only and safe for any authenticated user. The
    dashboard is a read view over existing tables; it does not introduce
    new persisted state.
    """
    with get_db() as conn:
        employees = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
        pay_periods = conn.execute("SELECT COUNT(*) AS n FROM pay_periods").fetchone()["n"]
        payslips = conn.execute("SELECT COUNT(*) AS n FROM payslips").fetchone()["n"]
        taxpayers = conn.execute("SELECT COUNT(*) AS n FROM taxpayers").fetchone()["n"]
        tax_returns = conn.execute("SELECT COUNT(*) AS n FROM tax_returns").fetchone()["n"]
        businesses = conn.execute("SELECT COUNT(*) AS n FROM businesses").fetchone()["n"]
        accounts = conn.execute("SELECT COUNT(*) AS n FROM accounts").fetchone()["n"]
        posted_entries = conn.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE status = 'posted'").fetchone()["n"]
        draft_entries = conn.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE status = 'draft'").fetchone()["n"]
        open_invoices = conn.execute("SELECT COUNT(*) AS n FROM invoices WHERE status = 'open'").fetchone()["n"]
        paid_invoices = conn.execute("SELECT COUNT(*) AS n FROM invoices WHERE status = 'paid'").fetchone()["n"]
        expenses = conn.execute("SELECT COUNT(*) AS n FROM expenses").fetchone()["n"]

        recent_payslips = [row_to_dict(row) for row in conn.execute(
            """SELECT payslips.id, payslips.created_at, payslips.gross_pay, payslips.net_pay,
               employees.name AS employee_name
               FROM payslips JOIN employees ON employees.id = payslips.employee_id
               ORDER BY payslips.created_at DESC LIMIT 5""").fetchall()]

        recent_entries = [row_to_dict(row) for row in conn.execute(
            """SELECT journal_entries.id, journal_entries.entry_date, journal_entries.description,
               journal_entries.status, businesses.legal_name AS business_name
               FROM journal_entries JOIN businesses ON businesses.id = journal_entries.business_id
               ORDER BY journal_entries.entry_date DESC, journal_entries.id DESC LIMIT 5""").fetchall()]

        recent_returns = [row_to_dict(row) for row in conn.execute(
            """SELECT tax_returns.id, tax_returns.tax_year, tax_returns.status,
               tax_returns.adjusted_gross_income, taxpayers.legal_name AS taxpayer_name
               FROM tax_returns JOIN taxpayers ON taxpayers.id = tax_returns.taxpayer_id
               ORDER BY tax_returns.updated_at DESC LIMIT 5""").fetchall()]

        return {
            "counts": {
                "employees": employees,
                "pay_periods": pay_periods,
                "payslips": payslips,
                "taxpayers": taxpayers,
                "tax_returns": tax_returns,
                "businesses": businesses,
                "accounts": accounts,
                "posted_entries": posted_entries,
                "draft_entries": draft_entries,
                "open_invoices": open_invoices,
                "paid_invoices": paid_invoices,
                "expenses": expenses,
            },
            "recent": {
                "payslips": recent_payslips,
                "entries": recent_entries,
                "returns": recent_returns,
            },
        }
