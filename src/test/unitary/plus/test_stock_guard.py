"""No roasting from an empty stock (owner rule 2026-10-23).

A coffee whose cloud stock is <= 0 must not be used for a NEW batch: carried over from the previous
batch, set by a schedule item, a blend component, or the chosen lot. The batch that crossed into minus
was roasted while the stock was still positive and is never blocked; this check only runs for the next
batch before CHARGE. check_selection is the pure decision; the canvas applies it.
"""

from plus.stock_guard import check_selection


def _stock(*coffees):
    return {'coffees': list(coffees), 'retrieved': 1.0}


def _c(hr_id, label, amounts, lots=None):
    c = {'hr_id': hr_id, 'label': label, 'origin': '',
         'stock': [{'location_hr_id': loc, 'location_label': loc, 'amount': a} for loc, a in amounts]}
    if lots is not None:
        c['lots'] = lots
    return c


def test_positive_stock_is_kept() -> None:
    # 2 kg left: this (minus-crossing) batch is allowed
    v = check_selection(_stock(_c('C1', 'Колумбия', [('S1', 2.0)])), 'C1', 'Колумбия', 'S1', None, None, None)
    assert not v.clear_coffee and v.messages == []


def test_zero_stock_clears_carried_coffee_with_message() -> None:
    v = check_selection(_stock(_c('C1', 'Колумбия', [('S1', 0.0)])), 'C1', 'Колумбия', 'S1', None, None, None)
    assert v.clear_coffee and v.clear_lot
    assert v.messages == ['Остаток „Колумбия“ — 0 кг. Оприходуйте зерно в облаке, чтобы жарить его.']


def test_store_specific_amount() -> None:
    s = _stock(_c('C1', 'Колумбия', [('S1', 0.0), ('S2', 30.0)]))
    assert check_selection(s, 'C1', 'Колумбия', 'S1', None, None, None).clear_coffee
    assert not check_selection(s, 'C1', 'Колумбия', 'S2', None, None, None).clear_coffee
    assert not check_selection(s, 'C1', 'Колумбия', None, None, None, None).clear_coffee   # no store: total


def test_coffee_missing_from_loaded_stock_is_out_of_stock() -> None:
    v = check_selection(_stock(_c('C2', 'Эфиопия', [('S1', 5.0)])), 'C1', 'Колумбия', 'S1', None, None, None)
    assert v.clear_coffee and 'Колумбия' in v.messages[0]


def test_unknown_stock_never_clears_and_never_crashes() -> None:
    for s in (None, {}, {'coffees': None}, 'garbage'):
        v = check_selection(s, 'C1', 'Колумбия', 'S1', 'L1', None, None)
        assert not v.clear_coffee and not v.clear_lot and not v.clear_blend and v.messages == []


def test_empty_or_missing_lot_is_cleared_coffee_kept() -> None:
    lots = [{'id': 'L1', 'code': 'EDU-1', 'weight_kg': 0.0}, {'id': 'L2', 'code': 'EDU-2', 'weight_kg': 40.0}]
    s = _stock(_c('C1', 'Колумбия', [('S1', 40.0)], lots))
    v = check_selection(s, 'C1', 'Колумбия', 'S1', 'L1', None, None)
    assert v.clear_lot and not v.clear_coffee and 'EDU-1' in v.messages[0]
    v = check_selection(s, 'C1', 'Колумбия', 'S1', 'L9', None, None)     # lot no longer sent = empty
    assert v.clear_lot and not v.clear_coffee
    assert not check_selection(s, 'C1', 'Колумбия', 'S1', 'L2', None, None).clear_lot


def test_lot_kept_when_server_sends_no_lot_list() -> None:
    s = _stock(_c('C1', 'Колумбия', [('S1', 40.0)]))
    assert not check_selection(s, 'C1', 'Колумбия', 'S1', 'L1', None, None).clear_lot


def _blend(*coffees):
    return {'label': 'Эспрессо', 'ingredients': [dict({'coffee': c, 'ratio': 0.5}, **extra) for c, extra in coffees]}


def test_blend_with_empty_component_is_cleared() -> None:
    s = _stock(_c('C1', 'Колумбия', [('S1', 20.0)]), _c('C2', 'Бразилия', [('S1', 0.0)]))
    v = check_selection(s, None, None, 'S1', None, _blend(('C1', {}), ('C2', {})), 'Эспрессо')
    assert v.clear_blend and not v.clear_coffee
    assert v.messages == ['В смеси „Эспрессо“ закончился „Бразилия“ (остаток 0 кг). Оприходуйте зерно в облаке, чтобы жарить эту смесь.']


def test_blend_component_with_stocked_replacement_is_ok() -> None:
    s = _stock(_c('C1', 'Колумбия', [('S1', 20.0)]), _c('C2', 'Бразилия', [('S1', 0.0)]),
               _c('C3', 'Перу', [('S1', 10.0)]))
    v = check_selection(s, None, None, 'S1', None, _blend(('C1', {}), ('C2', {'replace_coffee': 'C3'})), 'Эспрессо')
    assert not v.clear_blend and v.messages == []


def test_blend_all_stocked_is_kept() -> None:
    s = _stock(_c('C1', 'Колумбия', [('S1', 20.0)]), _c('C2', 'Бразилия', [('S1', 3.0)]))
    assert not check_selection(s, None, None, 'S1', None, _blend(('C1', {}), ('C2', {})), 'Эспрессо').clear_blend
