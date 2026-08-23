#
# ABOUT
# RoastArtisan Update Check

# LICENSE
# This program or module is free software: you can redistribute it and/or
# modify it under the terms of the GNU General Public License as published
# by the Free Software Foundation, either version 2 of the License, or
# version 3 of the License, or (at your option) any later version. It is
# provided for educational purposes and is distributed in the hope that
# it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See
# the GNU General Public License for more details.

# pure helpers for the update-check feature: no Qt, no network, so these
# can be unit tested in isolation from ApplicationWindow

import re


def parse_version(s: str) -> tuple:
    """Parse '4.0.3' / 'v4.0.3' / a git tag into a tuple of ints.

    A trailing non-numeric suffix (e.g. '-beta') is ignored. Returns ()
    on failure to parse any leading numeric component.
    """
    if not s:
        return ()
    match = re.match(r'v?(\d+(?:\.\d+)*)', s.strip())
    if match is None:
        return ()
    try:
        return tuple(int(part) for part in match.group(1).split('.'))
    except ValueError:
        return ()


def is_newer(latest: str, current: str) -> bool:
    """Return True if `latest` is a strictly newer version than `current`."""
    latest_v = parse_version(latest)
    current_v = parse_version(current)
    if not latest_v or not current_v:
        return False
    return latest_v > current_v


def select_asset(assets: list, system: str, machine: str) -> str | None:
    """Pick the download URL matching this platform from a GitHub release 'assets' list.

    `system`/`machine` are the values of platform.system()/platform.machine().
    Returns None if nothing matches.
    """
    if system == 'Windows':
        prefix, suffix = 'RoastArtisan-win-', '.zip'
    elif system == 'Darwin':
        if machine == 'arm64':
            prefix, suffix = 'RoastArtisan-mac-silicon-', '.dmg'
        else:
            # x86_64 or an unrecognized mac arch: the universal build runs everywhere
            prefix, suffix = 'RoastArtisan-mac-universal-', '.dmg'
    else:
        return None
    for asset in assets:
        name = asset.get('name', '')
        if name.startswith(prefix) and name.endswith(suffix):
            url = asset.get('browser_download_url')
            if url:
                return url
    return None
