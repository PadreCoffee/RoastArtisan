#!/usr/bin/env python3
"""Make every installed binary dependency universal2 (arm64 + x86_64).

Why this exists
---------------
``src/artisan-mac_universal.spec`` sets ``target_arch='universal2'``.  PyInstaller
refuses to produce a universal2 bundle unless *every* Mach-O binary it collects
already contains both slices; it raises ``IncompatibleBinaryArchError`` otherwise.

Several pinned dependencies (numpy, scipy, matplotlib, pillow, pydantic-core,
PyYAML, psutil, python-bidi, ...) do not publish ``universal2`` wheels any more --
only separate ``arm64`` and ``x86_64`` ones.  This script finds those, downloads
both single-architecture wheels and fuses them into a real universal2 wheel with
``delocate-merge`` (the tool upstream projects used to publish universal2 wheels),
then force-reinstalls the fused wheel.

The interpreter itself must be a universal2 build (python.org framework installer).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import sysconfig
from importlib.metadata import distributions
from pathlib import Path

MACHO_SUFFIXES = ('.so', '.dylib')

# pip needs an explicit set of platform tags when downloading for a foreign
# architecture.  pip picks the best match out of the list it is given.
ARM64_PLATFORMS = [
    'macosx_11_0_arm64', 'macosx_12_0_arm64', 'macosx_13_0_arm64',
    'macosx_14_0_arm64', 'macosx_15_0_arm64',
]
X86_64_PLATFORMS = [
    'macosx_10_9_x86_64', 'macosx_10_10_x86_64', 'macosx_10_12_x86_64',
    'macosx_10_13_x86_64', 'macosx_10_14_x86_64', 'macosx_10_15_x86_64',
    'macosx_11_0_x86_64', 'macosx_12_0_x86_64', 'macosx_13_0_x86_64',
    'macosx_14_0_x86_64', 'macosx_15_0_x86_64',
]


def macho_archs(path: Path) -> set[str] | None:
    """Return the architecture slices of a Mach-O file, or None if not Mach-O."""
    try:
        out = subprocess.run(['lipo', '-archs', str(path)], capture_output=True,
                             text=True, check=False)
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return set(out.stdout.split())


def thin_distributions(site_packages: Path) -> dict[str, str]:
    """Map distribution name -> version for every dist shipping a non-fat Mach-O."""
    thin: dict[str, str] = {}
    for dist in distributions():
        files = dist.files or []
        name = dist.metadata['Name']
        version = dist.version
        if not name:
            continue
        for rel in files:
            if not str(rel).endswith(MACHO_SUFFIXES):
                continue
            path = Path(dist.locate_file(rel))
            if not path.is_file():
                continue
            archs = macho_archs(path)
            if archs is None:
                continue
            if not {'arm64', 'x86_64'} <= archs:
                print(f'  thin: {name}=={version}  {rel}  archs={sorted(archs)}')
                thin[name] = version
                break
    return thin


def pip_download(spec: str, platforms: list[str], dest: Path, py_version: str,
                 abi_tags: list[str]) -> Path | None:
    dest.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, '-m', 'pip', 'download', '--no-deps',
           '--only-binary=:all:', '-d', str(dest),
           '--python-version', py_version, '--implementation', 'cp']
    for abi in abi_tags:
        cmd += ['--abi', abi]
    for plat in platforms:
        cmd += ['--platform', plat]
    cmd.append(spec)
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    wheels = sorted(dest.glob('*.whl'))
    if res.returncode != 0 or not wheels:
        print(f'    pip download failed for {spec} ({platforms[0]}...)')
        print('    ' + (res.stderr.strip().splitlines() or ['<no stderr>'])[-1])
        return None
    return wheels[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--workdir', default='universal2-wheels')
    args = parser.parse_args()

    plat = sysconfig.get_platform()
    print(f'interpreter platform: {plat}')
    if 'universal2' not in plat:
        print('ERROR: this interpreter is not a universal2 build; '
              'install the python.org universal2 framework build first.')
        return 2

    site_packages = Path(sysconfig.get_paths()['purelib'])
    py_version = '.'.join(map(str, sys.version_info[:2]))
    abi_tags = [f'cp{sys.version_info[0]}{sys.version_info[1]}', 'abi3', 'none']

    print(f'scanning {site_packages} for non-universal Mach-O binaries ...')
    thin = thin_distributions(site_packages)
    if not thin:
        print('nothing to do: every installed binary is already universal2')
        return 0

    print(f'\n{len(thin)} distribution(s) need fusing: '
          + ', '.join(f'{k}=={v}' for k, v in sorted(thin.items())))

    work = Path(args.workdir)
    if work.exists():
        shutil.rmtree(work)
    fused_dir = work / 'fused'
    fused_dir.mkdir(parents=True)

    failed: list[str] = []
    fused: list[Path] = []
    for name, version in sorted(thin.items()):
        spec = f'{name}=={version}'
        print(f'\n--- {spec}')
        arm = pip_download(spec, ARM64_PLATFORMS, work / 'arm64' / name,
                           py_version, abi_tags)
        intel = pip_download(spec, X86_64_PLATFORMS, work / 'x86_64' / name,
                             py_version, abi_tags)
        if arm is None or intel is None:
            failed.append(spec)
            continue
        if arm.name == intel.name:
            print(f'    single wheel serves both arches ({arm.name}); skipping')
            continue
        print(f'    arm64 : {arm.name}')
        print(f'    x86_64: {intel.name}')
        res = subprocess.run(['delocate-merge', str(arm), str(intel),
                              '-w', str(fused_dir)],
                             capture_output=True, text=True, check=False)
        if res.returncode != 0:
            print('    delocate-merge failed:')
            print('    ' + res.stderr.strip())
            failed.append(spec)
            continue
        print('    fused OK')

    fused = sorted(fused_dir.glob('*.whl'))
    if fused:
        print(f'\ninstalling {len(fused)} fused universal2 wheel(s) ...')
        subprocess.run([sys.executable, '-m', 'pip', 'install',
                        '--force-reinstall', '--no-deps', *map(str, fused)],
                       check=True)

    print('\nre-scanning for remaining non-universal binaries ...')
    remaining = thin_distributions(site_packages)
    if remaining:
        print('\nERROR: still non-universal after fusing: '
              + ', '.join(f'{k}=={v}' for k, v in sorted(remaining.items())))
        if failed:
            print('download/merge failures: ' + ', '.join(failed))
        return 1

    print('\nOK: every installed binary dependency is universal2')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
