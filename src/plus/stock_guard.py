#
# stock_guard.py
#
# ABOUT
# Roastlocal rule (2026-10-23): a coffee whose cloud stock is <= 0 cannot be used for a NEW batch until a
# receipt is entered in the cloud. The batch that crosses into minus is allowed (it started while the stock was
# positive); the next batch must not carry that coffee over from the previous batch, take it from a schedule
# item, use it as a blend component, or use an empty lot. The picker already hides coffees with stock <= 0;
# this module decides, for the coffee/lot/blend about to be roasted, what has to be cleared. It never blocks a
# batch or an upload (the cloud accepts every /aroast).
#
# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later version. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.

from dataclasses import dataclass, field
from typing import Any, Final

# amounts at or below this (kg) count as empty; same threshold the coffee picker uses (plus.stock.stock_epsilon)
EMPTY_EPSILON: Final[float] = 0.01


@dataclass
class StockVerdict:
    clear_coffee: bool = False
    clear_lot: bool = False
    clear_blend: bool = False
    messages: list[str] = field(default_factory=list)


def _coffees(stock:Any) -> list[dict[str, Any]]|None:
    if not isinstance(stock, dict):
        return None
    coffees = stock.get('coffees')
    return coffees if isinstance(coffees, list) else None


def _find(coffees:list[Any], hr_id:str|None) -> dict[str, Any]|None:
    if not hr_id:
        return None
    return next((c for c in coffees if isinstance(c, dict) and c.get('hr_id') == hr_id), None)


# remaining stock (kg) of a coffee in the given store, or over all stores if no store is selected
def _amount(coffee:dict[str, Any]|None, store:str|None) -> float:
    if coffee is None:
        return 0.0
    total = 0.0
    for s in coffee.get('stock') or []:
        if isinstance(s, dict) and (not store or s.get('location_hr_id') == store):
            try:
                total += float(s.get('amount') or 0)
            except (TypeError, ValueError):
                pass
    return total


def _label(coffee:dict[str, Any]|None, fallback:str|None, hr_id:str|None) -> str:
    if coffee is not None:
        try:
            from plus.stock import coffeeLabel
            lbl = coffeeLabel(coffee)  # type: ignore[arg-type]
            if isinstance(lbl, str) and lbl: # type: ignore[redundant-expr] # defensive
                return lbl
        except Exception:  # pylint: disable=broad-except
            pass
        if coffee.get('label'):
            return str(coffee['label'])
    return fallback or hr_id or '?'


def check_selection(stock:Any, coffee_hr_id:str|None, coffee_label:str|None, store_hr_id:str|None,
        lot_id:str|None, blend_spec:Any, blend_label:str|None) -> StockVerdict:
    """Decides what of the selection about to be roasted has no stock left. Unknown stock (not loaded,
    malformed) never clears anything."""
    verdict = StockVerdict()
    coffees = _coffees(stock)
    if coffees is None:
        return verdict
    if coffee_hr_id:
        coffee = _find(coffees, coffee_hr_id)
        label = _label(coffee, coffee_label, coffee_hr_id)
        if _amount(coffee, store_hr_id) <= EMPTY_EPSILON:
            verdict.clear_coffee = True
            verdict.clear_lot = True
            verdict.messages.append(f'Остаток „{label}“ — 0 кг. Оприходуйте зерно в облаке, чтобы жарить его.')
        elif lot_id and coffee is not None and isinstance(coffee.get('lots'), list):
            # the server sends only non-empty lots; a chosen lot that is missing or empty is used up
            lot = next((lt for lt in coffee['lots'] if isinstance(lt, dict) and lt.get('id') == lot_id), None)
            weight = 0.0
            if lot is not None:
                try:
                    weight = float(lot.get('weight_kg') or 0)
                except (TypeError, ValueError):
                    weight = 0.0
            if lot is None or weight <= EMPTY_EPSILON:
                verdict.clear_lot = True
                code = (lot or {}).get('code') or lot_id
                verdict.messages.append(f'Партия „{code}“ кофе „{label}“ закончилась. Будет использована партия по умолчанию.')
    if isinstance(blend_spec, dict):
        name = blend_label or str(blend_spec.get('label') or '?')
        for ing in blend_spec.get('ingredients') or []:
            if not isinstance(ing, dict) or not ing.get('coffee'):
                continue
            comp = _find(coffees, ing['coffee'])
            if _amount(comp, store_hr_id) > EMPTY_EPSILON:
                continue
            repl = ing.get('replace_coffee')
            if repl and _amount(_find(coffees, repl), store_hr_id) > EMPTY_EPSILON:
                continue  # the cloud's replacement coffee covers this component
            verdict.clear_blend = True
            verdict.messages.append(
                f'В смеси „{name}“ закончился „{_label(comp, None, ing["coffee"])}“ (остаток 0 кг). '
                'Оприходуйте зерно в облаке, чтобы жарить эту смесь.')
            break
    return verdict
