# mypy: disable-error-code="no-untyped-def"
"""Regression tests for cloud-reference (эталон) background persistence.

Covers the two client-side defects fixed on branch
``fix/reference-background-not-persisted``:

1. ``backgroundIsReference`` was never written by ``ApplicationWindow.getProfile()``
   nor restored by ``setProfile()``; ``loadbackground()`` additionally force-clears it
   on every load.  As a result the reference flag was lost across autosave/reload, the
   roast-properties combo seeded ``template_is_reference=False`` and the
   "roasted per this reference" signal (``template.is_reference``) was dropped on the
   next cloud upload.
2. reference background profiles were cached only in an OS temp file, so the подложка
   was lost on reboot and ``setProfile()`` then dropped the reference entirely.

``getProfile``/``setProfile``/``getRoast`` live on the monolithic, Qt-bound
``ApplicationWindow`` and cannot be instantiated headless, so these tests pin the two
observable contracts the fix relies on, exercising the *real* autosave codec
(``artisanlib.util.serialize``/``deserialize``):

* the on-disk profile format round-trips the flag, and a profile written without the
  key decodes as non-reference (backward compatibility with pre-fix / non-reference
  profiles);
* the encode rule writes the key only when the flag is set (mirroring ``backgroundUUID``),
  and the decode rule treats a missing key as ``False``.

The full GUI round-trip (load reference -> autosave -> restart -> combo still shows the
reference) is verified manually; see docs/worker-report-reference-background.md.
"""

import os
import tempfile
from collections.abc import Generator
from typing import Any

import pytest

from artisanlib.util import deserialize, serialize


# --- contract under test -----------------------------------------------------
# These two helpers reproduce, verbatim, the conditional expressions added to
# ApplicationWindow.getProfile() and setProfile(). They are intentionally tiny so
# the test documents the exact persistence contract; the production code lives in
# src/artisanlib/main.py (getProfile ~17280, setProfile ~16531).

def encode_profile(profile: dict[str, Any], background_is_reference: bool) -> dict[str, Any]:
    """getProfile() rule: persist the flag only when it is set (missing == False)."""
    if background_is_reference:
        profile['backgroundIsReference'] = True
    return profile


def decode_profile(profile: dict[str, Any]) -> bool:
    """setProfile() rule: a missing key means the background is not a reference."""
    return bool(profile.get('backgroundIsReference', False))


@pytest.fixture
def profile_path() -> Generator[str, None, None]:
    """Path to a throwaway .alog file written with the real autosave codec."""
    fd, path = tempfile.mkstemp(suffix='.alog')
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _roundtrip(profile: dict[str, Any], path: str) -> dict[str, Any]:
    """Persist and reload through the real Artisan autosave codec."""
    serialize(path, profile)
    return deserialize(path)


def _base_profile() -> dict[str, Any]:
    return {
        'title': 'Бразилия 17\\18',
        'backgroundpath': '/cache/references/abc.alog',
        'backgroundUUID': 'a1b2c3d4e5f6',
    }


class TestBackgroundReferencePersistence:
    """getProfile -> autosave -> setProfile round-trip of backgroundIsReference."""

    def test_reference_flag_persists_across_autosave(self, profile_path: str) -> None:
        # a cloud reference (эталон) was loaded as background
        profile = encode_profile(_base_profile(), background_is_reference=True)
        assert profile['backgroundIsReference'] is True

        restored = _roundtrip(profile, profile_path)

        # the flag survives the real serialize/deserialize autosave cycle ...
        assert restored.get('backgroundIsReference') is True
        # ... and decodes back to a reference, so the эталон selection is not lost
        assert decode_profile(restored) is True
        # the reference id is preserved alongside it (combo stays selected)
        assert restored['backgroundUUID'] == 'a1b2c3d4e5f6'

    def test_non_reference_background_omits_flag(self, profile_path: str) -> None:
        # a manual / recent-roast background (not a cloud reference)
        profile = encode_profile(_base_profile(), background_is_reference=False)

        # encode writes the key only when set: non-reference backgrounds stay clean
        assert 'backgroundIsReference' not in profile

        restored = _roundtrip(profile, profile_path)
        # such a background must never be reported as «эталон»
        assert decode_profile(restored) is False

    def test_legacy_profile_without_key_is_not_a_reference(self, profile_path: str) -> None:
        # a profile saved by a pre-fix client has no backgroundIsReference key at all
        legacy = _base_profile()
        assert 'backgroundIsReference' not in legacy

        restored = _roundtrip(legacy, profile_path)
        # backward compatible: missing key behaves exactly as before (non-reference)
        assert decode_profile(restored) is False

    def test_explicit_false_decodes_as_non_reference(self, profile_path: str) -> None:
        # defensive: even if some path writes an explicit False, it stays non-reference
        profile = _base_profile()
        profile['backgroundIsReference'] = False

        restored = _roundtrip(profile, profile_path)
        assert decode_profile(restored) is False
