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


def select_download(downloads: dict, system: str, machine: str) -> str | None:
    """Pick the download URL matching this platform from the cloud manifest's 'downloads' dict.

    `system`/`machine` are the values of platform.system()/platform.machine(). A platform
    slot with nothing published is absent from `downloads`. Returns None if nothing matches.
    """
    if system == 'Windows':
        key = 'win'
    elif system == 'Darwin':
        # x86_64 or an unrecognized mac arch: the universal build runs everywhere
        key = 'mac-silicon' if machine == 'arm64' else 'mac-universal'
    else:
        return None
    return downloads.get(key)
