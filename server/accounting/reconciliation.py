from __future__ import annotations

import datetime
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _date, _money, _require_business
from .reports import _account_balances


RECONCILIATION_STATUSES = {"open", "reconciled", "discrepancy"}


def list_reconciliations(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT reconciliations.*, accounts.code AS account_code, accounts.name AS account_name
            FROM reconciliations JOIN accounts ON accounts.id = reconciliations.account_id
            WHERE reconciliations.business_id = ? ORDER BY statement_date DESC, id DESC""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_reconciliation(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    try:
        account_id = int(data.get("account_id"))
    except (TypeError, ValueError):
        raise ValueError("account_id is required")
    statement_date = _date(data.get("statement_date"), "statement_date")
    statement_balance = _money(data.get("statement_balance"), "statement_balance")
    notes = str(data.get("notes", "")).strip()
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        account = conn.execute("SELECT account_type FROM accounts WHERE id = ? AND business_id = ? AND active = 1", (account_id, business_id)).fetchone()
        if account is None:
            raise ValueError("Account not found for this business")
        # Compute book balance from posted entries up to statement_date
        balances = _account_balances(conn, business_id, statement_date)
        acct_balance = next((row for row in balances if row["id"] == account_id), None)
        if acct_balance is None:
            book_balance = 0.0
        elif account["account_type"] in ("asset", "expense"):
            book_balance = round(acct_balance["debits"] - acct_balance["credits"], 2)
        else:
            book_balance = round(acct_balance["credits"] - acct_balance["debits"], 2)
        difference = round(statement_balance - book_balance, 2)
        status = "reconciled" if abs(difference) < 0.005 else "discrepancy"
        cursor = conn.execute(
            "INSERT INTO reconciliations (business_id, account_id, statement_date, statement_balance, book_balance, difference, status, notes, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (business_id, account_id, statement_date, statement_balance, book_balance, difference, status, notes, now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM reconciliations WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_reconciliation(reconciliation_id: int, data: dict[str, Any]) -> dict[str, Any]:
    notes = str(data.get("notes", "")).strip()
    status = str(data.get("status", "")).strip().lower()
    if status and status not in RECONCILIATION_STATUSES:
        raise ValueError("Invalid status")
    now = now_utc()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM reconciliations WHERE id = ?", (reconciliation_id,)).fetchone()
        if row is None:
            raise ValueError("Reconciliation not found")
        if status:
            conn.execute("UPDATE reconciliations SET status = ?, notes = ?, updated_at = ? WHERE id = ?", (status, notes, now, reconciliation_id))
        else:
            conn.execute("UPDATE reconciliations SET notes = ?, updated_at = ? WHERE id = ?", (notes, now, reconciliation_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM reconciliations WHERE id = ?", (reconciliation_id,)).fetchone())


def delete_reconciliation(reconciliation_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM reconciliations WHERE id = ?", (reconciliation_id,)).fetchone() is None:
            raise ValueError("Reconciliation not found")
        conn.execute("DELETE FROM reconciliations WHERE id = ?", (reconciliation_id,))
        conn.commit()


def list_bank_transactions(business_id: int, account_id: int | None = None, cleared: bool | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = "SELECT * FROM bank_transactions WHERE business_id = ?"
        params: list[Any] = [business_id]
        if account_id is not None:
            query += " AND account_id = ?"
            params.append(account_id)
        if cleared is not None:
            query += " AND cleared = ?"
            params.append(1 if cleared else 0)
        query += " ORDER BY transaction_date DESC, id DESC"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_bank_transaction(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    try:
        account_id = int(data.get("account_id"))
    except (TypeError, ValueError):
        raise ValueError("account_id is required")
    transaction_date = _date(data.get("transaction_date"), "transaction_date")
    description = str(data.get("description", "")).strip()
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        raise ValueError("amount must be a number")
    if amount <= 0:
        raise ValueError("amount must be positive")
    tx_type = str(data.get("type", "")).strip().lower()
    if tx_type not in ("deposit", "withdrawal", "fee", "interest"):
        raise ValueError("type must be one of: deposit, withdrawal, fee, interest")
    reference = str(data.get("reference", "")).strip()
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (account_id, business_id)).fetchone()
        if acct is None:
            raise ValueError("Account not found for this business")
        cursor = conn.execute(
            "INSERT INTO bank_transactions (business_id, account_id, transaction_date, description, amount, type, reference, cleared, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (business_id, account_id, transaction_date, description, amount, tx_type, reference, now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (cursor.lastrowid,)).fetchone())


def match_bank_transaction(transaction_id: int, journal_line_id: int) -> dict[str, Any]:
    with get_db() as conn:
        tx = conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone()
        if tx is None:
            raise ValueError("Bank transaction not found")
        tx = row_to_dict(tx)
        jl = conn.execute("SELECT * FROM journal_lines WHERE id = ?", (journal_line_id,)).fetchone()
        if jl is None:
            raise ValueError("Journal line not found")
        # Verify the journal line belongs to the same business
        je = conn.execute("SELECT business_id FROM journal_entries WHERE id = ?", (jl["entry_id"],)).fetchone()
        if je is None or je["business_id"] != tx["business_id"]:
            raise ValueError("Journal line does not belong to the same business")
        now = now_utc()
        conn.execute("UPDATE bank_transactions SET matched_journal_line_id = ?, cleared = 1, updated_at = ? WHERE id = ?", (journal_line_id, now, transaction_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone())


def unmatch_bank_transaction(transaction_id: int) -> dict[str, Any]:
    with get_db() as conn:
        tx = conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone()
        if tx is None:
            raise ValueError("Bank transaction not found")
        now = now_utc()
        conn.execute("UPDATE bank_transactions SET matched_journal_line_id = NULL, cleared = 0, updated_at = ? WHERE id = ?", (now, transaction_id))
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone())


def delete_bank_transaction(transaction_id: int) -> None:
    with get_db() as conn:
        if conn.execute("SELECT id FROM bank_transactions WHERE id = ?", (transaction_id,)).fetchone() is None:
            raise ValueError("Bank transaction not found")
        conn.execute("DELETE FROM bank_transactions WHERE id = ?", (transaction_id,))
        conn.commit()


def bank_reconciliation_summary(business_id: int, account_id: int) -> dict[str, Any]:
    with get_db() as conn:
        _require_business(conn, business_id)
        acct = conn.execute("SELECT * FROM accounts WHERE id = ? AND business_id = ?", (account_id, business_id)).fetchone()
        if acct is None:
            raise ValueError("Account not found for this business")
        acct = row_to_dict(acct)
        txs = conn.execute("SELECT * FROM bank_transactions WHERE business_id = ? AND account_id = ?", (business_id, account_id)).fetchall()
        txs = [row_to_dict(t) for t in txs]
        cleared = [t for t in txs if t["cleared"]]
        uncleared = [t for t in txs if not t["cleared"]]
        cleared_total = round(sum(t["amount"] if t["type"] in ("deposit", "interest") else -t["amount"] for t in cleared), 2)
        uncleared_total = round(sum(t["amount"] if t["type"] in ("deposit", "interest") else -t["amount"] for t in uncleared), 2)
        # Get book balance from posted entries
        balances = _account_balances(conn, business_id, datetime.date.today().isoformat())
        acct_balance = next((row for row in balances if row["id"] == account_id), None)
        if acct_balance is None:
            book_balance = 0.0
        elif acct["account_type"] in ("asset", "expense"):
            book_balance = round(acct_balance["debits"] - acct_balance["credits"], 2)
        else:
            book_balance = round(acct_balance["credits"] - acct_balance["debits"], 2)
        return {
            "account": acct,
            "total_transactions": len(txs),
            "cleared_count": len(cleared),
            "uncleared_count": len(uncleared),
            "cleared_total": cleared_total,
            "uncleared_total": uncleared_total,
            "book_balance": book_balance,
            "difference": round(book_balance - cleared_total, 2),
            "cleared_transactions": cleared,
            "uncleared_transactions": uncleared,
        }
