from __future__ import annotations

import datetime
from typing import Any
from payroll.db import get_db, now_utc, row_to_dict
from .ledger import _date, _is_period_closed, _post_operation_entry, _require_business


def list_depreciation_assets(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT da.*, a.code AS asset_code, aa.code AS accumulated_code, dp.code AS depreciation_code
               FROM depreciation_assets da
               LEFT JOIN accounts a ON a.id = da.asset_account_id
               LEFT JOIN accounts aa ON aa.id = da.accumulated_account_id
               LEFT JOIN accounts dp ON dp.id = da.depreciation_account_id
               WHERE da.business_id = ? ORDER BY da.acquisition_date DESC""",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def create_depreciation_asset(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    name = str(data.get("name", "")).strip()
    if not name:
        raise ValueError("name is required")
    try:
        asset_account_id = int(data.get("asset_account_id"))
        accumulated_account_id = int(data.get("accumulated_account_id"))
        depreciation_account_id = int(data.get("depreciation_account_id"))
    except (TypeError, ValueError):
        raise ValueError("asset_account_id, accumulated_account_id, and depreciation_account_id are required")
    try:
        cost = float(data.get("cost", 0))
    except (TypeError, ValueError):
        raise ValueError("cost must be a number")
    if cost <= 0:
        raise ValueError("cost must be positive")
    salvage_value = float(data.get("salvage_value", 0))
    if salvage_value < 0:
        raise ValueError("salvage_value must be >= 0")
    useful_life_months = int(data.get("useful_life_months", 0))
    if useful_life_months <= 0:
        raise ValueError("useful_life_months must be > 0")
    method = str(data.get("method", "straight_line")).strip().lower()
    if method not in ("straight_line", "declining_balance"):
        raise ValueError("method must be 'straight_line' or 'declining_balance'")
    depreciation_rate = float(data.get("depreciation_rate", 0))
    if depreciation_rate < 0 or depreciation_rate > 100:
        raise ValueError("depreciation_rate must be between 0 and 100")
    if method == "declining_balance" and depreciation_rate <= 0:
        raise ValueError("depreciation_rate is required for declining_balance method")
    acquisition_date = _date(data.get("acquisition_date"), "acquisition_date")
    start_date = _date(data.get("start_date", acquisition_date), "start_date")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        for aid in (asset_account_id, accumulated_account_id, depreciation_account_id):
            acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (aid, business_id)).fetchone()
            if acct is None:
                raise ValueError("Account not found for this business")
        cursor = conn.execute(
            "INSERT INTO depreciation_assets (business_id, name, asset_account_id, accumulated_account_id, depreciation_account_id, cost, salvage_value, useful_life_months, method, depreciation_rate, acquisition_date, start_date, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
            (business_id, name, asset_account_id, accumulated_account_id, depreciation_account_id, cost, salvage_value, useful_life_months, method, depreciation_rate, acquisition_date, start_date, now, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (cursor.lastrowid,)).fetchone())


def depreciation_schedule(asset_id: int) -> dict[str, Any]:
    """Calculate the depreciation schedule for an asset."""
    with get_db() as conn:
        asset = conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (asset_id,)).fetchone()
        if asset is None:
            raise ValueError("Depreciation asset not found")
        asset = row_to_dict(asset)
        depreciable_base = asset["cost"] - asset["salvage_value"]
        schedule: list[dict[str, Any]] = []
        if asset["method"] == "straight_line":
            monthly_depreciation = round(depreciable_base / asset["useful_life_months"], 2)
            start = datetime.date.fromisoformat(asset["start_date"])
            accumulated = 0.0
            for month in range(asset["useful_life_months"]):
                month_date = start
                for _ in range(month):
                    if month_date.month == 12:
                        month_date = month_date.replace(year=month_date.year + 1, month=1)
                    else:
                        month_date = month_date.replace(month=month_date.month + 1)
                # Adjust for rounding on last period
                if month == asset["useful_life_months"] - 1:
                    dep_amount = round(depreciable_base - accumulated, 2)
                else:
                    dep_amount = monthly_depreciation
                accumulated = round(accumulated + dep_amount, 2)
                schedule.append({
                    "period": month + 1,
                    "date": month_date.isoformat(),
                    "depreciation": dep_amount,
                    "accumulated": accumulated,
                    "book_value": round(asset["cost"] - accumulated, 2),
                })
        else:  # declining_balance
            rate = asset["depreciation_rate"] / 100
            start = datetime.date.fromisoformat(asset["start_date"])
            book_value = asset["cost"]
            accumulated = 0.0
            for month in range(asset["useful_life_months"]):
                month_date = start
                for _ in range(month):
                    if month_date.month == 12:
                        month_date = month_date.replace(year=month_date.year + 1, month=1)
                    else:
                        month_date = month_date.replace(month=month_date.month + 1)
                dep_amount = round(book_value * rate / 12, 2)
                # Don't depreciate below salvage value
                if book_value - dep_amount < asset["salvage_value"]:
                    dep_amount = round(book_value - asset["salvage_value"], 2)
                if dep_amount <= 0:
                    break
                book_value = round(book_value - dep_amount, 2)
                accumulated = round(accumulated + dep_amount, 2)
                schedule.append({
                    "period": month + 1,
                    "date": month_date.isoformat(),
                    "depreciation": dep_amount,
                    "accumulated": accumulated,
                    "book_value": book_value,
                })
        return {
            "asset": asset,
            "schedule": schedule,
            "total_depreciation": schedule[-1]["accumulated"] if schedule else 0,
            "final_book_value": schedule[-1]["book_value"] if schedule else asset["cost"],
        }


def post_depreciation(asset_id: int, through_date: str) -> dict[str, Any]:
    """Post a depreciation journal entry for an asset up to the given date."""
    through_date = _date(through_date, "through_date")
    with get_db() as conn:
        asset = conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (asset_id,)).fetchone()
        if asset is None:
            raise ValueError("Depreciation asset not found")
        asset = row_to_dict(asset)
        if asset["status"] != "active":
            raise ValueError("Asset is not active")
        if _is_period_closed(conn, asset["business_id"], through_date):
            raise ValueError("Cannot post to a closed accounting period")
        # Calculate depreciation amount up to through_date
        schedule = depreciation_schedule(asset_id)
        total_dep = 0.0
        for entry in schedule["schedule"]:
            if entry["date"] <= through_date:
                total_dep = entry["accumulated"]
            else:
                break
        if total_dep <= 0:
            raise ValueError("No depreciation to post for this period")
        # Only the incremental amount is posted: entries already linked to
        # this asset define what has been depreciated so far, so re-posting
        # the same period never duplicates depreciation.
        posted_rows = conn.execute(
            """SELECT COALESCE(SUM(jl.debit), 0) AS posted
               FROM journal_lines jl
               JOIN journal_entries je ON je.id = jl.entry_id
               WHERE je.depreciation_asset_id = ? AND je.status = 'posted'
               AND jl.account_id = ?""",
            (asset_id, asset["depreciation_account_id"]),
        ).fetchone()
        incremental = round(total_dep - round(posted_rows["posted"], 2), 2)
        if incremental <= 0:
            raise ValueError("No depreciation to post for this period")
        now = now_utc()
        # Create journal entry: debit depreciation expense, credit accumulated depreciation
        entry_id = _post_operation_entry(
            conn, asset["business_id"], through_date, f"DEP-{asset['id']}",
            f"Depreciation for {asset['name']}",
            [(asset["depreciation_account_id"], incremental, 0), (asset["accumulated_account_id"], 0, incremental)],
            depreciation_asset_id=asset_id,
        )
        # Check if fully depreciated
        if total_dep >= (asset["cost"] - asset["salvage_value"]):
            conn.execute("UPDATE depreciation_assets SET status = 'fully_depreciated', updated_at = ? WHERE id = ?", (now, asset_id))
        conn.commit()
        return {"posted": True, "amount": incremental, "entry_id": entry_id}


def fixed_asset_register(business_id: int) -> dict[str, Any]:
    """Comprehensive fixed asset register with current book values."""
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            """SELECT da.*, a.code AS asset_code, a.name AS asset_account_name,
               aa.code AS accumulated_code, aa.name AS accumulated_account_name,
               dp.code AS depreciation_code, dp.name AS depreciation_account_name
               FROM depreciation_assets da
               LEFT JOIN accounts a ON a.id = da.asset_account_id
               LEFT JOIN accounts aa ON aa.id = da.accumulated_account_id
               LEFT JOIN accounts dp ON dp.id = da.depreciation_account_id
               WHERE da.business_id = ?
               ORDER BY da.acquisition_date DESC, da.id DESC""",
            (business_id,),
        ).fetchall()
        assets = []
        total_cost = 0.0
        total_accumulated = 0.0
        total_book_value = 0.0
        for row in rows:
            asset = row_to_dict(row)
            # Calculate accumulated depreciation from entries linked to this
            # asset only — sharing an accumulated-depreciation account must not
            # aggregate depreciation across unrelated assets.
            dep_rows = conn.execute(
                """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS accumulated
                   FROM journal_lines jl
                   JOIN journal_entries je ON je.id = jl.entry_id
                   WHERE je.business_id = ? AND je.status = 'posted'
                   AND je.depreciation_asset_id = ?
                   AND jl.account_id = ?""",
                (business_id, asset["id"], asset["accumulated_account_id"]),
            ).fetchone()
            accumulated_dep = round(dep_rows["accumulated"], 2)
            book_value = round(asset["cost"] - accumulated_dep, 2)
            total_cost = round(total_cost + asset["cost"], 2)
            total_accumulated = round(total_accumulated + accumulated_dep, 2)
            total_book_value = round(total_book_value + book_value, 2)
            asset["accumulated_depreciation"] = accumulated_dep
            asset["book_value"] = book_value
            assets.append(asset)
        return {
            "assets": assets,
            "total_assets": len(assets),
            "total_cost": total_cost,
            "total_accumulated_depreciation": total_accumulated,
            "total_book_value": total_book_value,
        }


def dispose_fixed_asset(asset_id: int, disposal_date: str, disposal_price: float, gain_loss_account_id: int) -> dict[str, Any]:
    """Dispose of a fixed asset, creating journal entries for the disposal."""
    disposal_date = _date(disposal_date, "disposal_date")
    try:
        disposal_price = float(disposal_price)
    except (TypeError, ValueError):
        raise ValueError("disposal_price must be a number")
    try:
        gain_loss_account_id = int(gain_loss_account_id)
    except (TypeError, ValueError):
        raise ValueError("gain_loss_account_id is required")
    now = now_utc()
    with get_db() as conn:
        asset = conn.execute("SELECT * FROM depreciation_assets WHERE id = ?", (asset_id,)).fetchone()
        if asset is None:
            raise ValueError("Asset not found")
        asset = row_to_dict(asset)
        if asset["status"] not in ("active", "fully_depreciated"):
            raise ValueError("Asset is not active or fully depreciated")
        if _is_period_closed(conn, asset["business_id"], disposal_date):
            raise ValueError("Cannot post to a closed accounting period")
        # Verify gain/loss account
        acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (gain_loss_account_id, asset["business_id"])).fetchone()
        if acct is None:
            raise ValueError("Gain/loss account not found for this business")
        # Calculate accumulated depreciation — only entries belonging to this
        # asset, so disposal never consumes another asset's depreciation.
        dep_rows = conn.execute(
            """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) AS accumulated
               FROM journal_lines jl
               JOIN journal_entries je ON je.id = jl.entry_id
               WHERE je.business_id = ? AND je.status = 'posted'
               AND je.depreciation_asset_id = ?
               AND jl.account_id = ?""",
            (asset["business_id"], asset_id, asset["accumulated_account_id"]),
        ).fetchone()
        accumulated_dep = round(dep_rows["accumulated"], 2)
        book_value = round(asset["cost"] - accumulated_dep, 2)
        gain_loss = round(disposal_price - book_value, 2)
        # Create disposal journal entry through the common posting layer
        lines = [(asset["asset_account_id"], 0, asset["cost"])]
        if accumulated_dep > 0:
            lines.append((asset["accumulated_account_id"], accumulated_dep, 0))
        if disposal_price > 0:
            lines.append((gain_loss_account_id, disposal_price, 0))
        if gain_loss > 0:
            lines.append((gain_loss_account_id, 0, gain_loss))
        elif gain_loss < 0:
            lines.append((gain_loss_account_id, abs(gain_loss), 0))
        entry_id = _post_operation_entry(
            conn, asset["business_id"], disposal_date, f"DISP-{asset['id']}",
            f"Disposal of {asset['name']}", lines,
        )
        # Mark asset as disposed
        conn.execute("UPDATE depreciation_assets SET status = 'disposed', updated_at = ? WHERE id = ?", (now, asset_id))
        conn.commit()
        return {
            "disposed": True,
            "asset_id": asset_id,
            "disposal_price": disposal_price,
            "book_value": book_value,
            "gain_loss": gain_loss,
            "entry_id": entry_id,
        }
