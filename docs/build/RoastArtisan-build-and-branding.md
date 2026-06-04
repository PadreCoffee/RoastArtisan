# RoastArtisan — build & branding notes

Scope of the de-branding pass: **visible product identity only**. The internal
file format (`.alog`), the `artisan://` URL scheme, the file-association class IDs
(`Artisan.Profile`, …) and the cloud API endpoints are intentionally left intact
for backward compatibility.

## Build scripts

| Target | Script | Output | Spec |
|--------|--------|--------|------|
| Windows x64 (portable + installer) | `build-windows-x64-local.bat` (repo root) | `src/dist/RoastArtisan/RoastArtisan.exe` + `src/RoastArtisan-win-x64-<ver>-setup.exe` | `artisan-win-local.spec` + `setup-install3-pi.nsi` |
| Windows installer (Qt already installed) | `src/build-win-installer.bat` | `src/RoastArtisan-win-x64-<ver>-setup.exe` | `artisan-win-local.spec` + `setup-install3-pi.nsi` |
| macOS Apple Silicon (arm64) | `build-macos-silicon-local.sh` (repo root) **NEW** | `src/dist/RoastArtisan.app` + `src/RoastArtisan-mac-<ver>.dmg` | `artisan-mac.spec` (`target_arch='arm64'`) |

- Regenerate derived UI/help/translation files first with `RUN_DERIVED=1` (off by
  default; generated files are committed).
- `build-macos3.sh` remains the Appveyor **CI-only** script (it exits unless
  `$APPVEYOR` is set); `build-macos-silicon-local.sh` is its local counterpart.

## Icons

- App / exe icon: `roastartisan.ico` (Windows), `roastartisan.icns` (macOS app bundle),
  `roastartisan.png` (in-app window icon, loaded by `artisanlib/main.py`).
- Fix applied: both `artisan-win-local.spec` and `artisan-mac.spec` now bundle
  `roastartisan.png` (previously the win spec shipped the unused `artisan.png` and the
  mac spec shipped neither, so the in-app window icon was missing).
- The per-file-type icons (`artisanProfile.ico`, `artisanAlarms.ico`, …) are kept as-is.

## Visible-identity changes applied

- `artisanlib/__init__.py` — release-sponsor name/domain/url set to empty: removes the
  `– artisan.plus (Release Sponsor)` line from the window title, the "sponsored by
  artisan.plus" chart watermark and the sponsor click-through.
- `plus/config.py` — added `app_display_name = 'RoastArtisan'` for user-facing cloud
  text. `app_name` (`= 'artisan.plus'`) is **kept** because it is the OS keyring service
  name for saved credentials; changing it would log existing users out.
- `plus/queue.py`, `plus/schedule.py` — upload/login/schedule UI messages now show
  `RoastArtisan` instead of `artisan.plus`.
- `artisanlib/main.py` — About dialog footer shows the product name (was an
  `artisan-scope.org` link); exported PDF/PNG/SVG metadata now read `RoastArtisan v…`.
- `setup-install3-pi.nsi` — installer product name, publisher, shortcuts, install dir,
  exe name (`RoastArtisan.exe`), output dir (`dist/RoastArtisan`), main icon
  (`roastartisan.ico`) and association descriptions rebranded; `artisan://` scheme and
  file-class IDs preserved.
- App name (`artisanlib/util.py: application_name = 'RoastArtisan'`) and QSettings org
  were already RoastArtisan before this pass.

## Russian translation

`src/translations/artisan_ru.qm` was verified to be byte-identical to a fresh `lrelease`
of `artisan_ru.ts` — the latest Russian translation is current and will bundle correctly.
(Both files are modified in the working tree as part of ongoing translation work.)

## Deliberately NOT changed (flagged for a later decision)

These still reference Artisan and would need the owner's own domain/endpoints or a
larger i18n pass:

1. **Translatable UI strings** that literally contain "Artisan" (e.g. `Menu` "Artisan
   CSV…/JSON…", the one-time welcome messages, "The Artisan Team"). Editing the English
   source strings would desync all ~30 translation files; this is a separate i18n task.
2. **External help/update/donate URLs** still pointing at `artisan-scope.org`:
   `helpHelp()` (Help → online help), `checkUpdate()` (version check) and the donate link.
   They need a RoastArtisan equivalent URL before they can be repointed.
3. **Cloud API defaults** in `plus/config.py` (`default_api_base_url = https://artisan.plus/...`)
   — functional endpoints, left untouched; the live cloud is configured at runtime.
4. **Keyring service name** (`app_name = 'artisan.plus'`) — kept for saved-login
   compatibility. Flip it to `'RoastArtisan'` only if a one-time re-login is acceptable.
