from __future__ import annotations

from typing import Any

from payroll.db import get_db, now_utc, row_to_dict


def _require_business(conn, business_id: int) -> None:
    row = conn.execute("SELECT id FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if row is None:
        raise ValueError("Business not found")


def list_items(business_id: int, active_only: bool = False) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = "SELECT * FROM inventory_items WHERE business_id = ?"
        params: list[Any] = [business_id]
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY sku"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def create_item(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    sku = str(data.get("sku", "")).strip()
    name = str(data.get("name", "")).strip()
    if not sku or not name:
        raise ValueError("sku and name are required")
    description = str(data.get("description", "")).strip()
    unit_cost = float(data.get("unit_cost", 0))
    unit_price = float(data.get("unit_price", 0))
    if unit_cost < 0 or unit_price < 0:
        raise ValueError("unit_cost and unit_price must be >= 0")
    quantity_on_hand = float(data.get("quantity_on_hand", 0))
    reorder_point = float(data.get("reorder_point", 0))
    if reorder_point < 0:
        raise ValueError("reorder_point must be >= 0")
    inventory_account_id = data.get("inventory_account_id")
    cogs_account_id = data.get("cogs_account_id")
    sales_account_id = data.get("sales_account_id")
    active = 1 if data.get("active", True) else 0
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        for aid in (inventory_account_id, cogs_account_id, sales_account_id):
            if aid is not None:
                acct = conn.execute("SELECT id FROM accounts WHERE id = ? AND business_id = ?", (aid, business_id)).fetchone()
                if acct is None:
                    raise ValueError("Account not found for this business")
        try:
            cursor = conn.execute(
                "INSERT INTO inventory_items (business_id, sku, name, description, unit_cost, unit_price, quantity_on_hand, reorder_point, inventory_account_id, cogs_account_id, sales_account_id, active, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (business_id, sku, name, description, unit_cost, unit_price, quantity_on_hand, reorder_point, inventory_account_id, cogs_account_id, sales_account_id, active, now, now),
            )
        except Exception:
            raise ValueError("SKU already exists for this business")
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (cursor.lastrowid,)).fetchone())


def update_item(item_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ValueError("Inventory item not found")
        updates: list[str] = []
        params: list[Any] = []
        for field in ("name", "description"):
            val = data.get(field)
            if val is not None:
                updates.append(f"{field} = ?")
                params.append(str(val).strip())
        for field in ("unit_cost", "unit_price", "reorder_point"):
            val = data.get(field)
            if val is not None:
                val = float(val)
                if val < 0:
                    raise ValueError(f"{field} must be >= 0")
                updates.append(f"{field} = ?")
                params.append(val)
        if "active" in data:
            updates.append("active = ?")
            params.append(1 if data["active"] else 0)
        if updates:
            updates.append("updated_at = ?")
            params.append(now_utc())
            conn.execute(f"UPDATE inventory_items SET {', '.join(updates)} WHERE id = ?", [*params, item_id])
            conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM inventory_items WHERE id = ?", (item_id,)).fetchone())


def delete_item(item_id: int) -> None:
    with get_db() as conn:
        row = conn.execute("SELECT id FROM inventory_items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise ValueError("Inventory item not found")
        conn.execute("DELETE FROM inventory_items WHERE id = ?", (item_id,))
        conn.commit()


def record_movement(data: dict[str, Any]) -> dict[str, Any]:
    try:
        business_id = int(data.get("business_id"))
    except (TypeError, ValueError):
        raise ValueError("business_id is required")
    try:
        item_id = int(data.get("item_id"))
    except (TypeError, ValueError):
        raise ValueError("item_id is required")
    movement_type = str(data.get("movement_type", "")).strip().lower()
    if movement_type not in ("purchase", "sale", "adjustment", "return"):
        raise ValueError("movement_type must be one of: purchase, sale, adjustment, return")
    quantity = float(data.get("quantity", 0))
    if quantity == 0:
        raise ValueError("quantity must be non-zero")
    unit_cost = float(data.get("unit_cost", 0))
    reference = str(data.get("reference", "")).strip()
    movement_date = str(data.get("movement_date", "")).strip()
    if not movement_date:
        raise ValueError("movement_date is required")
    now = now_utc()
    with get_db() as conn:
        _require_business(conn, business_id)
        item = conn.execute("SELECT * FROM inventory_items WHERE id = ? AND business_id = ?", (item_id, business_id)).fetchone()
        if item is None:
            raise ValueError("Inventory item not found for this business")
        item = row_to_dict(item)
        # Adjust quantity: purchase/return increases, sale/adjustment can be +/- 
        if movement_type in ("purchase", "return"):
            new_qty = item["quantity_on_hand"] + abs(quantity)
        elif movement_type == "sale":
            new_qty = item["quantity_on_hand"] - abs(quantity)
            if new_qty < 0:
                raise ValueError("Insufficient inventory for this sale")
        else:  # adjustment
            new_qty = item["quantity_on_hand"] + quantity
        conn.execute("UPDATE inventory_items SET quantity_on_hand = ?, updated_at = ? WHERE id = ?", (new_qty, now, item_id))
        cursor = conn.execute(
            "INSERT INTO inventory_movements (business_id, item_id, movement_type, quantity, unit_cost, reference, movement_date, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (business_id, item_id, movement_type, quantity, unit_cost, reference, movement_date, now),
        )
        conn.commit()
        return row_to_dict(conn.execute("SELECT * FROM inventory_movements WHERE id = ?", (cursor.lastrowid,)).fetchone())


def list_movements(business_id: int, item_id: int | None = None) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        query = "SELECT im.*, ii.sku, ii.name FROM inventory_movements im JOIN inventory_items ii ON ii.id = im.item_id WHERE im.business_id = ?"
        params: list[Any] = [business_id]
        if item_id:
            query += " AND im.item_id = ?"
            params.append(item_id)
        query += " ORDER BY im.movement_date DESC, im.id DESC"
        return [row_to_dict(row) for row in conn.execute(query, params).fetchall()]


def low_stock_report(business_id: int) -> list[dict[str, Any]]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute(
            "SELECT * FROM inventory_items WHERE business_id = ? AND active = 1 AND quantity_on_hand <= reorder_point ORDER BY sku",
            (business_id,),
        ).fetchall()
        return [row_to_dict(row) for row in rows]


def inventory_valuation(business_id: int) -> dict[str, Any]:
    with get_db() as conn:
        _require_business(conn, business_id)
        rows = conn.execute("SELECT * FROM inventory_items WHERE business_id = ? AND active = 1", (business_id,)).fetchall()
        items = [row_to_dict(row) for row in rows]
        total_cost_value = round(sum(i["quantity_on_hand"] * i["unit_cost"] for i in items), 2)
        total_retail_value = round(sum(i["quantity_on_hand"] * i["unit_price"] for i in items), 2)
        return {
            "item_count": len(items),
            "total_cost_value": total_cost_value,
            "total_retail_value": total_retail_value,
            "potential_profit": round(total_retail_value - total_cost_value, 2),
            "items": items,
        }
