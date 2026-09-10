from __future__ import annotations

from typing import Any

from payroll.db import get_db, row_to_dict


def _require_business(conn, business_id: int) -> None:
    row = conn.execute("SELECT id FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if row is None:
        raise ValueError("Business not found")


def financial_calendar(business_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    """Return upcoming financial events for a business within a date range."""
    with get_db() as conn:
        _require_business(conn, business_id)
        events: list[dict[str, Any]] = []

        # Overdue and upcoming invoices
        invoices = conn.execute(
            """SELECT id, invoice_number, customer_id, issue_date, due_date, amount, amount_paid, status
               FROM invoices WHERE business_id = ? AND status = 'open'
               AND due_date >= ? AND due_date <= ? ORDER BY due_date""",
            (business_id, start_date, end_date),
        ).fetchall()
        for inv in invoices:
            balance = round(inv["amount"] - inv["amount_paid"], 2)
            events.append({
                "date": inv["due_date"],
                "type": "invoice_due",
                "title": f"Invoice {inv['invoice_number']} due",
                "amount": balance,
                "entity_id": inv["id"],
            })

        # Recurring expenses due
        recurring = conn.execute(
            """SELECT id, description, amount, next_date
               FROM recurring_expenses WHERE business_id = ? AND active = 1
               AND next_date >= ? AND next_date <= ? ORDER BY next_date""",
            (business_id, start_date, end_date),
        ).fetchall()
        for rec in recurring:
            events.append({
                "date": rec["next_date"],
                "type": "recurring_expense",
                "title": f"Recurring: {rec['description']}",
                "amount": rec["amount"],
                "entity_id": rec["id"],
            })

        # Pending reconciliations (open or discrepancy)
        reconciliations = conn.execute(
            """SELECT id, account_id, statement_date, status
               FROM reconciliations WHERE business_id = ? AND status != 'reconciled'
               AND statement_date >= ? AND statement_date <= ? ORDER BY statement_date""",
            (business_id, start_date, end_date),
        ).fetchall()
        for recon in reconciliations:
            events.append({
                "date": recon["statement_date"],
                "type": "reconciliation",
                "title": f"Reconciliation pending for account {recon['account_id']}",
                "amount": None,
                "entity_id": recon["id"],
            })

        # Budgets for the period
        budgets = conn.execute(
            """SELECT id, account_id, fiscal_year, period, budgeted_amount
               FROM budgets WHERE business_id = ?
               AND fiscal_year >= ? AND fiscal_year <= ?""",
            (business_id, start_date[:4], end_date[:4]),
        ).fetchall()
        for budget in budgets:
            events.append({
                "date": f"{budget['fiscal_year']}-01-01",
                "type": "budget",
                "title": f"Budget for {budget['period']} {budget['fiscal_year']}",
                "amount": budget["budgeted_amount"],
                "entity_id": budget["id"],
            })

        events.sort(key=lambda e: e["date"])
        return {"start_date": start_date, "end_date": end_date, "events": events, "total": len(events)}
