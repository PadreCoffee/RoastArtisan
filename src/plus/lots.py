#
# lots.py
#
# Pure, Qt-free helpers for "lot selection at roast" (Roastlocal Cloud lots mode).
#
# The cloud adds an additive `lots` array to each /acoffees coffee row, present ONLY in
# lots mode and ONLY for single green-bean coffees (blends have no lots):
#
#   lots: [ { "id": "<uuid>", "code": "<lot_code>", "weight_kg": <float kg>,
#             "warehouse_id": "<uuid|null>", "warehouse_name": "<str|null>" } ]
#
# Cloud-locked contract (2026-09-04):
#  - weight_kg is the lot's current remaining stock, in kg.
#  - the SERVER already excludes empty lots (only weight_kg > 0 are sent) — no client >0 filter.
#  - the array is ordered by the cloud's auto-allocation order (priority ASC, created_at ASC);
#    the FIRST element is the lot the cloud picks by default when no lot_id is uploaded.
#  - write path: include the chosen lot's id as `lot_id` in the /aroast upload; omit it and the
#    cloud auto-allocates by priority (today's behaviour, always safe).
#
# UI/semantics decided with the cloud master:
#  - show a lot dropdown ONLY when a coffee has MORE THAN ONE pickable lot (len > 1).
#  - pre-select the first lot (the cloud default) — or a previously chosen lot on reopen.
#  - "roaster changes nothing" (leaves the pre-selected default at index 0) == deduct by priority
#    == today's behaviour == upload NO lot_id. Only an explicit non-default pick (index > 0)
#    uploads a lot_id.

from typing import Any


def pickable_lots(lots:Any) -> list[dict[str, Any]]:
    """Well-formed lot entries, order preserved (the cloud's auto-allocation order).

    Defensive only: keeps dicts carrying a non-empty string `id`. Empty-stock lots are already
    excluded server-side (locked contract), so weight is NOT filtered here — trust the server.
    A missing/None/non-list `lots` (SKU mode, or a coffee with no lots) yields []."""
    if not isinstance(lots, list):
        return []
    result:list[dict[str, Any]] = []
    for lot in lots:
        if isinstance(lot, dict) and isinstance(lot.get('id'), str) and lot['id']:
            result.append(lot)
    return result


def show_lot_dropdown(lots:Any) -> bool:
    """True only when the coffee has more than one pickable lot (the gate for the dropdown).
    0/1/absent -> no dropdown, behave exactly as today (cloud auto-allocates)."""
    return len(pickable_lots(lots)) > 1


def default_lot_index(lots:Any, chosen_lot_id:str|None) -> int:
    """The combo index to pre-select: a previously chosen lot if it is still present (survives a
    dialog reopen), otherwise 0 — the cloud's default (first by priority)."""
    pl = pickable_lots(lots)
    if chosen_lot_id:
        for i, lot in enumerate(pl):
            if lot.get('id') == chosen_lot_id:
                return i
    return 0


def selected_lot_id(index:int, lots:Any) -> str|None:
    """The lot_id to upload for the given combo index. Index 0 is the pre-selected cloud default
    -> None (omit lot_id, auto-allocate by priority = today's behaviour). An explicit non-default
    pick (index > 0, in range) -> that lot's id. Out-of-range/absent -> None (safe)."""
    pl = pickable_lots(lots)
    if 0 < index < len(pl):
        lot_id = pl[index].get('id')
        return lot_id if isinstance(lot_id, str) and lot_id else None
    return None


def lot_option_label(lot:dict[str, Any], weight_str:str) -> str:
    """Dropdown label for a lot: `code · <weight> · <warehouse>`. `weight_str` is pre-rendered by
    the caller in the roaster's unit (lots.py stays Qt/unit-free). warehouse_name is a label and may
    be absent/None (lots are aggregate across warehouses). Falls back to the lot id tail if no code."""
    code = str(lot.get('code') or '').strip() or (str(lot.get('id') or '')[:8])
    parts:list[str] = [code]
    ws = (weight_str or '').strip()
    if ws:
        parts.append(ws)
    warehouse = str(lot.get('warehouse_name') or '').strip()
    if warehouse:
        parts.append(warehouse)
    return ' · '.join(parts)
