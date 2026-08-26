#
# schedule_references.py
#
# Pure (Qt-free, network-free) helpers for the scheduler reference picker (эталоны).
#
# The scheduler shows a reference dropdown on the selected task only when its
# coffee/blend resolves to >=2 references; picking one loads that reference as the
# chart background (client-side, not persisted). These two functions encode the
# "show the picker?" and "which entry is the default?" rules and live here, apart
# from the Qt/network code in plus/schedule.py, so they can be unit-tested headlessly.

from typing import Final


# Minimum number of references for the picker to be offered. Fewer than this and the
# single/server default template is loaded silently, exactly as before this feature.
MIN_REFERENCES_FOR_PICKER: Final[int] = 2


# True iff a reference picker should be offered for this reference list.
def reference_picker_applies(references: list[dict]) -> bool:
    return len(references) >= MIN_REFERENCES_FOR_PICKER


# Index (into the cloud-ordered `references` list) to pre-select in the picker:
# the entry whose normalized uuid hex matches the task's server default template,
# else 0 (the first, i.e. the cloud's lot-matched/newest entry). Returns -1 for an
# empty list. `default_hex` is a UUID.hex (no dashes) or None.
def pick_default_reference_index(references: list[dict], default_hex: str | None) -> int:
    if not references:
        return -1
    if default_hex:
        for i, r in enumerate(references):
            if r.get('uuid') == default_hex:
                return i
    return 0
