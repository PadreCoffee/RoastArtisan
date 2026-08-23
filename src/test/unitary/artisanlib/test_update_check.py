"""Unit tests for artisanlib.update_check (pure helpers, no Qt, no network)."""

from artisanlib.update_check import is_newer, parse_version, select_asset


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


def _asset(name: str) -> dict:
    return {'name': name, 'browser_download_url': f'https://example.com/{name}'}


def test_select_asset_windows() -> None:
    assets = [_asset('RoastArtisan-win-4.0.10.zip'), _asset('RoastArtisan-mac-universal-4.0.10.dmg')]
    assert select_asset(assets, 'Windows', 'AMD64') == 'https://example.com/RoastArtisan-win-4.0.10.zip'


def test_select_asset_mac_arm64_picks_silicon() -> None:
    assets = [
        _asset('RoastArtisan-mac-silicon-4.0.10.dmg'),
        _asset('RoastArtisan-mac-universal-4.0.10.dmg'),
    ]
    assert select_asset(assets, 'Darwin', 'arm64') == 'https://example.com/RoastArtisan-mac-silicon-4.0.10.dmg'


def test_select_asset_mac_x86_64_picks_universal() -> None:
    assets = [
        _asset('RoastArtisan-mac-silicon-4.0.10.dmg'),
        _asset('RoastArtisan-mac-universal-4.0.10.dmg'),
    ]
    assert select_asset(assets, 'Darwin', 'x86_64') == 'https://example.com/RoastArtisan-mac-universal-4.0.10.dmg'


def test_select_asset_mac_unknown_arch_picks_universal() -> None:
    assets = [
        _asset('RoastArtisan-mac-silicon-4.0.10.dmg'),
        _asset('RoastArtisan-mac-universal-4.0.10.dmg'),
    ]
    assert select_asset(assets, 'Darwin', 'ppc') == 'https://example.com/RoastArtisan-mac-universal-4.0.10.dmg'


def test_select_asset_no_match_returns_none() -> None:
    assets = [_asset('RoastArtisan-win-4.0.10.zip')]
    assert select_asset(assets, 'Linux', 'x86_64') is None
    assert select_asset([], 'Windows', 'AMD64') is None
