"""Unit tests for plus.lots — the pure lot-selection helpers.

Like test_schedule_references.py, plus.lots is deliberately Qt-free and network-free, so these
tests need no PyQt preamble and are immune to the suite's Qt global-state flakiness.
"""

from plus.lots import (
    pickable_lots,
    show_lot_dropdown,
    default_lot_index,
    selected_lot_id,
    lot_option_label,
)


def _lot(id_: str, code: str = '', weight_kg: float = 1.0, warehouse: str | None = None) -> dict:
    d: dict = {'id': id_, 'code': code, 'weight_kg': weight_kg}
    if warehouse is not None:
        d['warehouse_name'] = warehouse
    return d


A = _lot('a' * 8, 'L-A', 12.5, 'WH-1')
B = _lot('b' * 8, 'L-B', 5.0, 'WH-2')
C = _lot('c' * 8, 'L-C', 3.0)


# --- pickable_lots: tolerant of SKU mode / malformed --------------------------------------------

def test_pickable_lots_absent_or_sku_mode_is_empty() -> None:
    assert pickable_lots(None) == []          # SKU mode: field absent
    assert pickable_lots([]) == []
    assert pickable_lots('nonsense') == []     # not a list


def test_pickable_lots_drops_malformed_keeps_order() -> None:
    lots = [A, {'code': 'no-id'}, {'id': ''}, 42, B]
    assert pickable_lots(lots) == [A, B]       # order preserved, malformed dropped


# --- show_lot_dropdown: the gate is strictly len > 1 --------------------------------------------

def test_dropdown_gate() -> None:
    assert show_lot_dropdown(None) is False
    assert show_lot_dropdown([A]) is False     # exactly one lot -> no dropdown, auto-allocate
    assert show_lot_dropdown([A, B]) is True
    assert show_lot_dropdown([A, B, C]) is True


# --- selected_lot_id: index 0 = default = OMIT; index > 0 = explicit non-default -----------------

def test_selected_lot_id_index0_omits() -> None:
    # roaster left the pre-selected default (index 0) -> omit lot_id (today's behaviour)
    assert selected_lot_id(0, [A, B, C]) is None


def test_selected_lot_id_nondefault_sends_that_lot() -> None:
    assert selected_lot_id(1, [A, B, C]) == B['id']
    assert selected_lot_id(2, [A, B, C]) == C['id']


def test_selected_lot_id_out_of_range_is_none() -> None:
    assert selected_lot_id(5, [A, B]) is None
    assert selected_lot_id(-1, [A, B]) is None
    assert selected_lot_id(1, []) is None


# --- default_lot_index: pre-select prior choice, else 0 (cloud default) --------------------------

def test_default_lot_index_no_prior_is_zero() -> None:
    assert default_lot_index([A, B, C], None) == 0


def test_default_lot_index_prior_choice_survives_reopen() -> None:
    assert default_lot_index([A, B, C], C['id']) == 2


def test_default_lot_index_prior_choice_gone_falls_back_to_zero() -> None:
    assert default_lot_index([A, B], 'zzzzzzzz') == 0


# --- lot_option_label: code · weight · warehouse, tolerant of missing pieces ---------------------

def test_lot_option_label_full() -> None:
    assert lot_option_label(A, '12.5 kg') == 'L-A · 12.5 kg · WH-1'


def test_lot_option_label_no_warehouse() -> None:
    assert lot_option_label(C, '3 kg') == 'L-C · 3 kg'


def test_lot_option_label_missing_code_falls_back_to_id_tail() -> None:
    lot = {'id': 'deadbeef1234', 'weight_kg': 1.0}
    assert lot_option_label(lot, '1 kg') == 'deadbeef · 1 kg'
