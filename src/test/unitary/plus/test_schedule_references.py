#
# Unit tests for the pure scheduler reference-picker helpers.
#
# These import plus.schedule_references directly: it is deliberately Qt-free and
# network-free, so these tests do not need the PyQt mocking preamble the other
# plus/ tests use and are immune to the suite's Qt global-state flakiness.

from plus.schedule_references import (
    reference_picker_applies,
    pick_default_reference_index,
    MIN_REFERENCES_FOR_PICKER,
)


def _ref(uuid: str, label: str = '') -> dict:
    return {'uuid': uuid, 'label': label or uuid[:4]}


class TestReferencePickerApplies:
    def test_empty_list_no_picker(self) -> None:
        assert reference_picker_applies([]) is False

    def test_single_reference_no_picker(self) -> None:
        # 1 reference -> keep today's behaviour (silent single-template load), no dropdown
        assert reference_picker_applies([_ref('a' * 32)]) is False

    def test_two_references_show_picker(self) -> None:
        assert reference_picker_applies([_ref('a' * 32), _ref('b' * 32)]) is True

    def test_many_references_show_picker(self) -> None:
        assert reference_picker_applies([_ref(str(i) * 32) for i in range(5)]) is True

    def test_threshold_constant(self) -> None:
        assert MIN_REFERENCES_FOR_PICKER == 2


class TestPickDefaultReferenceIndex:
    def test_empty_returns_minus_one(self) -> None:
        assert pick_default_reference_index([], 'a' * 32) == -1

    def test_no_default_selects_first(self) -> None:
        refs = [_ref('a' * 32), _ref('b' * 32)]
        assert pick_default_reference_index(refs, None) == 0

    def test_default_present_selects_it(self) -> None:
        refs = [_ref('a' * 32), _ref('b' * 32), _ref('c' * 32)]
        assert pick_default_reference_index(refs, 'b' * 32) == 1
        assert pick_default_reference_index(refs, 'c' * 32) == 2

    def test_default_absent_falls_back_to_first(self) -> None:
        # NEGATIVE CONTROL: a server default that is not among the fetched references
        # must fall back to the first entry (never -1, never a crash), so the picker
        # still shows a sensible pre-selection.
        refs = [_ref('a' * 32), _ref('b' * 32)]
        assert pick_default_reference_index(refs, 'z' * 32) == 0

    def test_empty_string_default_selects_first(self) -> None:
        refs = [_ref('a' * 32), _ref('b' * 32)]
        assert pick_default_reference_index(refs, '') == 0
