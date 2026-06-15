# Worker report — reference background (эталон / подложка) not persisted

**Branch:** `fix/reference-background-not-persisted` (from `master`)
**Scope:** client-side only. The cloud/server side was confirmed clean by the master
(every reference has coffee+green_bean+machine bindings, `profile_upload_status=uploaded_ok`,
a full profile blob, and the `coffee_hr_id`+machine query returns them). No server/API
calls or reference-discovery code were touched.

## Summary

For cloud references (эталон) the selected reference / background (подложка) was lost
after autosave + reopen/restart: the roast-properties reference selector fell back to
«Без эталона» and the "roasted per this reference" signal was dropped on the next upload.
Two independent client defects combined to cause this. Both are now fixed with minimal,
surgical edits to `src/artisanlib/main.py`.

---

## Defect 1 — `backgroundIsReference` was never persisted

### Root cause (confirmed by reading the code)

The flag `qmc.backgroundIsReference` distinguishes a genuine cloud reference (эталон)
from a manual / recent-roast background that merely shares a `backgroundUUID`. Its value
was never saved and never restored:

- `ApplicationWindow.getProfile()` wrote `backgroundpath` and `backgroundUUID` but **not**
  `backgroundIsReference` (was `src/artisanlib/main.py` ~17276–17281).
- `loadbackground()` force-sets `self.qmc.backgroundIsReference = False` on **every** load
  (`src/artisanlib/main.py:14498`) — by design, since the cloud-reference selector
  re-flags it `True` afterwards.
- `setProfile()` reloaded the background but never restored the flag
  (`src/artisanlib/main.py` background block ~16517–16559).

Data flow of the bug: load reference → `backgroundIsReference=True` → autosave drops it →
reload leaves it `False` → on reopening Roast Properties, `roast_properties.py:637` seeds
`self.template_is_reference = bool(self.aw.qmc.backgroundIsReference)` = `False` → on save,
`roast_properties.py:6144`/`6166` commits `backgroundIsReference=False` → the upload
consumer `plus/roast.py:423` (`if getattr(aw.qmc,'backgroundIsReference',False): ...`)
drops `template.is_reference`. The reference signal is silently lost.

### Fix

- **`getProfile()`** — persist the flag, mirroring the "only write when set" style of
  `backgroundUUID` (so missing key == `False`, fully backward compatible):

  ```python
  if self.qmc.backgroundIsReference:
      profile['backgroundIsReference'] = True
  ```

- **`setProfile()`** — after the background-restore block, re-apply the flag from the
  profile (a missing key means non-reference; `loadbackground()` already cleared it, so we
  re-apply here, and only when a background is actually loaded):

  ```python
  if (not quiet) and self.qmc.backgroundprofile is not None:
      self.qmc.backgroundIsReference = bool(profile.get('backgroundIsReference', False))
  ```

`loadbackground()` is intentionally left untouched: it still defaults the flag to `False`,
and the authoritative value is re-applied by `setProfile()` (restore path) and by the
reference selector in `roast_properties.py` (interactive path). Non-reference backgrounds
(manual file / recent roast) never write the key and therefore stay `False`.

---

## Defect 2 — reference background cached only in an OS temp file

### Root cause (confirmed by reading the code)

- `fetchRemoteBackgroundProfile()` cached the fetched reference into an OS temp file via
  `tempfile.mkstemp(prefix='roastartisan-background-…')` and registered that temp path
  (was `src/artisanlib/main.py` ~14149–14155). OS temp dirs are cleared on reboot.
- On restore, `setProfile()` tried `profile['backgroundpath']`, then
  `plus.register.getPath(UUID)`; if both pointed at the now-deleted temp file it called
  `deleteBackground()` **without** re-fetching from the server (was
  `src/artisanlib/main.py` ~16527–16528). Result after reboot: подложка lost,
  `backgroundUUID → None` → «Без эталона».

`loadbackgroundUUID()` (`src/artisanlib/main.py:14162`) already implemented the correct
"register path → on miss, `fetchRemoteBackgroundProfile`" fallback; `setProfile()` simply
did not use it.

### Fix (two parts)

1. **Persistent cache** in `fetchRemoteBackgroundProfile()` — cache reference profiles in a
   persistent app-data dir keyed by the **full** UUID (`<AppLocalData>/references/<UUID>.alog`
   via the existing `getDataDirectory()` helper) instead of an OS temp file. This survives
   reboots, so the common restore path (`backgroundpath` exists) just works. Falls back to a
   temp file only if the data directory is unavailable.

2. **Re-fetch on miss** in `setProfile()` — when the cached/register path is gone but a
   `backgroundUUID` is present, re-fetch via `fetchRemoteBackgroundProfile(UUID)` and load it
   (emitting `fileDirtySignal` so the now-persistent path is re-saved) instead of
   `deleteBackground()`. This is the safety net (cache eviction / legacy profiles that still
   reference an old temp path) and makes the restore self-healing.

---

## Files & lines changed

`src/artisanlib/main.py` only (3 surgical edits):

1. `getProfile()` — added the `backgroundIsReference` write right after the `backgroundUUID`
   write (~17280).
2. `setProfile()` background-restore block (~16541–16564):
   - replaced the inner `else: self.deleteBackground()` with a remote re-fetch-on-miss
     (defect 2, part 2);
   - added the `backgroundIsReference` restore after the block (defect 1).
3. `fetchRemoteBackgroundProfile()` (~14149–14168) — persistent UUID-keyed cache with a
   temp-file fallback (defect 2, part 1).

New test: `src/test/unitary/artisanlib/test_background_reference.py`.

No refactors, no reformatting, no dependency changes, no API/server-contract changes,
reference discovery (`getReferencesFromAPI`, the `coffee_hr_id`+machine query) untouched.

---

## What was reproduced / verified

### Unit tests
- New `test_background_reference.py` (4 tests) — **all pass**. They exercise the *real*
  Artisan autosave codec (`artisanlib.util.serialize`/`deserialize`) and lock the
  persistence contract: a reference round-trips as a reference; a non-reference background
  omits the key; a legacy/pre-fix profile without the key decodes as non-reference
  (backward compatible); an explicit `False` stays non-reference.
- Full unit suite (`src/test/unitary`): **53 failed, 2232 passed, 3 skipped**, identical
  failure set to the pre-change baseline (**53 failed, 2228 passed, 3 skipped**) — the only
  delta is the 4 new passing tests. The 53 baseline failures are pre-existing and unrelated
  (Qt/`sys.modules` mock contamination and fork drift in `test_login`, `test_register`,
  `test_sync`, `test_roast`, `test_kaleido`, etc.; some require `hypothesis`/`pytest-qt`
  which had to be installed locally).

> Note on test scope: `getProfile`/`setProfile`/`getRoast` are methods of the monolithic,
> Qt-bound `ApplicationWindow` and cannot be instantiated headless, so the unit test pins
> the observable on-disk contract rather than driving those methods directly. The full GUI
> round-trip is covered by the manual steps below.

---

## Item D — residual findings (Бразилия 17\18 / 14\16, and the backslash)

- **Backslash in the coffee name is NOT a factor (refuted).** The background reference
  cache filename is now the pure-hex `"<UUID>.alog"`; the stored `backgroundpath` is that
  UUID-based path. The coffee title «Бразилия 17\18» is only a data field (`title`), never
  part of any background filesystem path. Additionally
  `removeDisallowedFilenameChars()` (`main.py:12988-12990`) strips `\ / < > : " | ? *` from
  autosave *foreground* filenames. So no Windows path break is expected from the backslash;
  «17\18» and «14\16» are simply the owner's most-used coffees — the defect is general.

- **"A different / old подложка loads" facet — mitigated.** The previous temp-file cache
  used a `UUID[:12]` prefix and OS-assigned temp paths; combined with `register` entries
  pointing at reused/stale temp paths, a restore could surface a wrong/old подложка. The new
  cache is keyed by the **full** UUID with a deterministic filename, and `setProfile()`
  re-fetches by UUID on any miss, so the loaded file is always the one matching
  `backgroundUUID`. Residual risk: `setProfile()`'s first branch still loads
  `profile['backgroundpath']` if that file exists without re-checking its UUID — harmless now
  because the path is UUID-named and content can no longer be replaced under a reused path,
  but worth keeping in mind if the cache filename scheme ever changes.

- **No residual loss path identified** for the reported symptom after B+C: the flag now
  survives autosave/reload, and the подложка is recoverable from the server by UUID even
  after the local cache is cleared.

---

## How the owner verifies on the Windows client

1. Open a profile for «Бразилия 17\18», open **Roast Properties → reference combo**, select
   the cloud reference (эталон). Confirm the подложка is drawn.
2. Trigger autosave (or save the profile), then **close and reopen** the profile.
   - Expected: the подложка is drawn again **and** the reference combo still shows the
     reference selected (not «Без эталона»).
3. Simulate the reboot/temp-clear case: with the app closed, delete the cached reference
   file (now under the RoastArtisan app-data dir — Windows:
   `%LOCALAPPDATA%\RoastArtisan\references\<UUID>.alog`; macOS:
   `~/Library/Application Support/RoastArtisan/references/<UUID>.alog` — previously it was in
   the Windows `%TEMP%` folder), then reopen the profile.
   - Expected: the client re-fetches the reference from the server by UUID, the подложка
     reloads, and the combo still shows the reference.
4. Re-upload the roast and confirm on the cloud that it is still marked as roasted per the
   reference (the `is_reference` signal is preserved).
5. Repeat with «14\16».

To watch it happen, run with debug logging enabled; relevant log lines:
`background profile loaded: …`, `remote background profile cached for <UUID> at …references…`,
and (on the miss path) the re-fetch followed by `background profile loaded`.

## Residual risk

- Low. Changes are additive and backward compatible: profiles without the new key behave
  exactly as before, non-reference backgrounds are unaffected (`is_reference` stays `False`),
  and the temp-file path remains as a fallback when the app data dir is unavailable.
- Old profiles still pointing at a now-deleted `%TEMP%` path self-heal on next open via the
  re-fetch, which then re-saves the persistent path (one `fileDirtySignal`/save).
