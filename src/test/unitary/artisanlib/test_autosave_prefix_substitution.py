"""Regression test for autosave filename token substitution (Cyrillic / RU-locale crash).

Reported bug: on some coffees autosave produced files named after the raw prefix template, e.g.
"~title ~dropbt ~dtr% ~date 1" -- the ~tokens were never substituted. Root cause: on RU locale
the ~mmm/~ddd fields were built via encodeLocal(), which turns a Cyrillic month/day (e.g. "июн")
into the literal text "\\u0438\\u044e\\u043d" (backslash escapes). Passing that to re.sub() AS A
REPLACEMENT TEMPLATE raises re.error: bad escape \\u -- and re.sub parses the template eagerly,
so it raised even when ~mmm wasn't present -- which aborted the whole substitution loop and left
the filename as the raw template (so every roast collided and got an incrementing suffix).

ApplicationWindow._substituteAutosaveFields substitutes each value LITERALLY via a replacement
function, so no value (Cyrillic via encodeLocal, a user-typed backslash, group-ref-like text)
can raise re.error and abort filename generation.
"""

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication(sys.argv)
_app.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)

import artisanlib.main as main_module  # noqa: E402


def _sub(fn: str, fields: 'list[tuple[str,str]]') -> str:
    return main_module.ApplicationWindow._substituteAutosaveFields(fn, fields)


def test_cyrillic_encodelocal_value_does_not_abort() -> None:
    # value exactly as encodeLocal('июн') produced it -- literal backslash-u escapes
    fields = [('title', 'Кофе'), ('mmm', '\\u0438\\u044e\\u043d'), ('date', '26-06-17')]
    out = _sub('~title ~date ~mmm', fields)
    assert out == 'Кофе 26-06-17 \\u0438\\u044e\\u043d'   # everything substituted, no crash


def test_backslash_and_groupref_value_is_literal() -> None:
    # a value that looks like regex backreferences must be inserted verbatim, not interpreted
    out = _sub('~title', [('title', r'a\1b\g<0>')])
    assert out == r'a\1b\g<0>'


def test_happy_path_substitution() -> None:
    out = _sub('~title_~date', [('title', 'Brazil'), ('date', '26-06-17')])
    assert out == 'Brazil_26-06-17'
