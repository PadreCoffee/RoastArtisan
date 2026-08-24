"""Unit tests for artisanlib.update_check (pure helpers, no Qt, no network)."""

from artisanlib.update_check import is_newer, parse_version, select_download


def test_parse_version_plain() -> None:
    assert parse_version('4.0.3') == (4, 0, 3)


def test_parse_version_v_prefix() -> None:
    assert parse_version('v4.0.3') == (4, 0, 3)


def test_parse_version_beta_suffix() -> None:
    assert parse_version('4.0.3-beta') == (4, 0, 3)


def test_parse_version_malformed() -> None:
    assert parse_version('not-a-version') == ()
    assert parse_version('') == ()


def test_is_newer_true() -> None:
    assert is_newer('4.0.10', '4.0.3') is True


def test_is_newer_equal_is_false() -> None:
    assert is_newer('4.0.3', '4.0.3') is False


def test_is_newer_older_is_false() -> None:
    assert is_newer('4.0.2', '4.0.3') is False


def test_is_newer_v_prefix() -> None:
    assert is_newer('v4.0.10', '4.0.3') is True


def test_is_newer_malformed_is_false() -> None:
    assert is_newer('not-a-version', '4.0.3') is False
    assert is_newer('4.0.10', 'not-a-version') is False


_DOWNLOADS = {
    'mac-silicon': 'https://roastlocal.ru/dl/mac-silicon',
    'mac-universal': 'https://roastlocal.ru/dl/mac-universal',
    'win': 'https://roastlocal.ru/dl/win',
}


def test_select_download_windows() -> None:
    assert select_download(_DOWNLOADS, 'Windows', 'AMD64') == 'https://roastlocal.ru/dl/win'


def test_select_download_mac_arm64_picks_silicon() -> None:
    assert select_download(_DOWNLOADS, 'Darwin', 'arm64') == 'https://roastlocal.ru/dl/mac-silicon'


def test_select_download_mac_x86_64_picks_universal() -> None:
    assert select_download(_DOWNLOADS, 'Darwin', 'x86_64') == 'https://roastlocal.ru/dl/mac-universal'


def test_select_download_mac_unknown_arch_picks_universal() -> None:
    assert select_download(_DOWNLOADS, 'Darwin', 'ppc') == 'https://roastlocal.ru/dl/mac-universal'


def test_select_download_unknown_system_returns_none() -> None:
    assert select_download(_DOWNLOADS, 'Linux', 'x86_64') is None


def test_select_download_missing_key_returns_none() -> None:
    assert select_download({'mac-universal': 'https://roastlocal.ru/dl/mac-universal'}, 'Windows', 'AMD64') is None
    assert select_download({}, 'Darwin', 'arm64') is None
