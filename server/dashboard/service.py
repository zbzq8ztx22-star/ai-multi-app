from __future__ import annotations

from typing import Any

from payroll.db import get_db, row_to_dict


def overview(user_id: int | None = None) -> dict[str, Any]:
    """Aggregate high-level counts and recent activity across modules.

    All counts are read-only and safe for any authenticated user. The
    dashboard is a read view over existing tables; it does not introduce
    new persisted state. Business-scoped figures are limited to the
    businesses the user can access.
    """
    with get_db() as conn:
        if user_id is None:
            allowed = conn.execute("SELECT id FROM businesses").fetchall()
        else:
            allowed = conn.execute(
                "SELECT business_id AS id FROM user_business_access WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        allowed_ids = [row["id"] for row in allowed]
        if allowed_ids:
            marks = ",".join("?" * len(allowed_ids))
            scope = f"business_id IN ({marks})"
            scope_args: tuple[Any, ...] = tuple(allowed_ids)
        else:
            scope = "1 = 0"
            scope_args = ()

        employees = conn.execute("SELECT COUNT(*) AS n FROM employees").fetchone()["n"]
        pay_periods = conn.execute("SELECT COUNT(*) AS n FROM pay_periods").fetchone()["n"]
        payslips = conn.execute("SELECT COUNT(*) AS n FROM payslips").fetchone()["n"]
        taxpayers = conn.execute("SELECT COUNT(*) AS n FROM taxpayers").fetchone()["n"]
        tax_returns = conn.execute("SELECT COUNT(*) AS n FROM tax_returns").fetchone()["n"]
        businesses = len(allowed_ids)
        accounts = conn.execute(f"SELECT COUNT(*) AS n FROM accounts WHERE {scope}", scope_args).fetchone()["n"]
        posted_entries = conn.execute(f"SELECT COUNT(*) AS n FROM journal_entries WHERE status = 'posted' AND {scope}", scope_args).fetchone()["n"]
        draft_entries = conn.execute(f"SELECT COUNT(*) AS n FROM journal_entries WHERE status = 'draft' AND {scope}", scope_args).fetchone()["n"]
        open_invoices = conn.execute(f"SELECT COUNT(*) AS n FROM invoices WHERE status = 'open' AND {scope}", scope_args).fetchone()["n"]
        paid_invoices = conn.execute(f"SELECT COUNT(*) AS n FROM invoices WHERE status = 'paid' AND {scope}", scope_args).fetchone()["n"]
        expenses = conn.execute(f"SELECT COUNT(*) AS n FROM expenses WHERE {scope}", scope_args).fetchone()["n"]

        recent_payslips = [row_to_dict(row) for row in conn.execute(
            """SELECT payslips.id, payslips.created_at, payslips.gross_pay, payslips.net_pay,
               employees.name AS employee_name
               FROM payslips JOIN employees ON employees.id = payslips.employee_id
               ORDER BY payslips.created_at DESC LIMIT 5""").fetchall()]

        recent_entries = [row_to_dict(row) for row in conn.execute(
            f"""SELECT journal_entries.id, journal_entries.entry_date, journal_entries.description,
               journal_entries.status, businesses.legal_name AS business_name
               FROM journal_entries JOIN businesses ON businesses.id = journal_entries.business_id
               WHERE {scope}
               ORDER BY journal_entries.entry_date DESC, journal_entries.id DESC LIMIT 5""",
            scope_args).fetchall()]

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


def trends(business_id: int, months: int = 6) -> dict[str, Any]:
    """Month-over-month revenue, expenses, and net income trends."""
    import datetime
    if months < 1 or months > 24:
        raise ValueError("months must be between 1 and 24")
    with get_db() as conn:
        row = conn.execute("SELECT id FROM businesses WHERE id = ?", (business_id,)).fetchone()
        if row is None:
            raise ValueError("Business not found")
        today = datetime.date.today()
        results: list[dict[str, Any]] = []
        for i in range(months - 1, -1, -1):
            month_date = datetime.date(today.year, today.month, 1)
            for _ in range(i):
                if month_date.month == 1:
                    month_date = month_date.replace(year=month_date.year - 1, month=12)
                else:
                    month_date = month_date.replace(month=month_date.month - 1)
            month_start = month_date.isoformat()
            if month_date.month == 12:
                month_end = month_date.replace(day=31).isoformat()
            else:
                next_month = month_date.replace(month=month_date.month + 1)
                month_end = (next_month - datetime.timedelta(days=1)).isoformat()
            # Revenue: credits - debits for revenue accounts
            rev_rows = conn.execute(
                """SELECT jl.debit, jl.credit FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   JOIN accounts a ON a.id = jl.account_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND je.entry_date >= ? AND je.entry_date <= ?
                   AND a.account_type = 'revenue'""",
                (business_id, month_start, month_end),
            ).fetchall()
            revenue = round(sum(r["credit"] - r["debit"] for r in rev_rows), 2)
            # Expenses: debits - credits for expense accounts
            exp_rows = conn.execute(
                """SELECT jl.debit, jl.credit FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   JOIN accounts a ON a.id = jl.account_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND je.entry_date >= ? AND je.entry_date <= ?
                   AND a.account_type = 'expense'""",
                (business_id, month_start, month_end),
            ).fetchall()
            expenses = round(sum(r["debit"] - r["credit"] for r in exp_rows), 2)
            net_income = round(revenue - expenses, 2)
            results.append({
                "month": month_start,
                "revenue": revenue,
                "expenses": expenses,
                "net_income": net_income,
            })
        # Calculate trends
        if len(results) >= 2:
            prev = results[-2]
            curr = results[-1]
            rev_change = round(curr["revenue"] - prev["revenue"], 2)
            exp_change = round(curr["expenses"] - prev["expenses"], 2)
            ni_change = round(curr["net_income"] - prev["net_income"], 2)
        else:
            rev_change = exp_change = ni_change = 0.0
        return {
            "business_id": business_id,
            "months": results,
            "changes": {
                "revenue": rev_change,
                "expenses": exp_change,
                "net_income": ni_change,
            },
        }
