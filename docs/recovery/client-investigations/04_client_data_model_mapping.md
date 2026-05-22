# Client Investigation: Artisan Client Concepts to Roastlocal Cloud Concept Mapping

## 1. Research question

How are Artisan client concepts mapped to Roastlocal Cloud concepts, specifically for Coffee, GreenBean, Lot, Batch, Roast, Roast profile, Reference, roast curves, controls, phase events, inventory fields, QC/cupping, and sticker/print/export fields?

## 2. Executive summary

The modified client uses an Artisan Plus-compatible API contract as the integration boundary (`src/plus/*`), with the main concept mapping implemented in `plus.roast.getTemplate()/getRoast()` for outbound payloads and `plus.sync.applyServerUpdates()` for inbound payloads.

Important finding: only a subset of Artisan roast metadata is sent in JSON to `/aroast`; detailed profile internals (including curve arrays and control timelines like Air/Drum/Burner events) are primarily transported via full `.alog` profile upload (`/roasts/{roast_id}/upload-profile`) when enabled. Therefore, terminology overlap does not imply identical semantic scope.

## 3. Files inspected

- `src/plus/roast.py`
- `src/plus/sync.py`
- `src/plus/stock.py`
- `src/plus/queue.py`
- `src/plus/config.py`
- `src/plus/schedule.py`
- `src/test/sanity/data/artisan/profile1.json`
- `docs/recovery/client-investigations/02_cloud_integration_boundary.md`
- `docs/recovery/client-investigations/03_http_network_layer.md`

## 4. Facts from code

### 4.1 Canonical API concept endpoints

- Stock/inventory and scheduling concept envelope is fetched from `stock_url = /acoffees` (`src/plus/config.py:205`, `src/plus/stock.py:118-141`, `src/plus/stock.py:263-266` where response `result` is accepted).
- Roast summary/update payloads are sent to `roast_url = /aroast` (`src/plus/config.py:206`, `src/plus/queue.py:516`).
- Reference profiles are queried from `/roasts/references` (`src/plus/config.py:211`, `src/plus/stock.py:1805-1835`).
- Full profile payload is uploaded as file to `/roasts/{roast_id}/upload-profile` (`src/plus/config.py:209`, `src/plus/queue.py:531-571`).

### 4.2 Outbound roast mapping layer

- `plus.roast.getTemplate()` maps internal roast/profile fields to cloud keys (batch, weights, environmental data, phase temperatures/times, AUC, etc.) (`src/plus/roast.py:40-255`).
- `plus.roast.getRoast()` converts `id -> roast_id`, `start_weight -> amount`, injects `coffee/blend/location`, cupping fields, notes, optional template, and modified timestamp (`src/plus/roast.py:285-428`).

### 4.3 Inbound roast mapping layer

- `plus.sync.applyServerUpdates()` maps server response fields back into local Artisan `qmc` fields, including default reconstruction for suppressed nulls and coffee/blend object de-structuring (`src/plus/sync.py:445-747`).

### 4.4 Sync semantics that affect meaning

- Zero/empty/default values are intentionally suppressed to `None` before upload and reconstructed on read (`src/plus/sync.py:317-327`, `src/plus/sync.py:455-465`).
- Not all outbound fields are expected inbound; `sync_record_zero_supressed_attributes_unsynced` are explicitly one-way from client to server (`src/plus/roast.py:451-482`, `src/plus/sync.py:718-722`).

## 5. Network/API behavior

- `/aroast` acts as both create/update channel and fetch channel (`GET /aroast/{uuid}`) with `200/204/404` semantics (`src/plus/sync.py:781-885`).
- A full roast record for upload must include at least `roast_id`, `date`, `amount`; partial update requires `roast_id` (`src/plus/queue.py:576-615`).
- Full profile transfer is a separate queue item and can succeed/fail independently from roast summary upload (`src/plus/queue.py:531-571`, `src/plus/queue.py:635-641`).

## 6. Data model mapping

### 6.1 Coffee / GreenBean / Lot / Inventory concepts

| Concept | Artisan/internal source field | Roastlocal Cloud request field | Roastlocal Cloud response field | Transformation / adaptation logic | Required vs optional | Risk if changed | Unclear assumptions |
|---|---|---|---|---|---|---|---|
| Coffee identity attached to roast | `aw.qmc.plus_coffee` | `coffee` (hr_id string in `/aroast` payload) | `coffee.hr_id`, `coffee.label` object in `/aroast/{id}` response | Outbound sends scalar id; inbound expects object and extracts `hr_id/label` (`src/plus/roast.py:366-373`, `src/plus/sync.py:551-564`) | Optional; explicit `None` is sent to clear | High: scalar vs object contract mismatch breaks sync | “Coffee” in roast sync appears to mean inventory item reference, not full bean spec |
| Coffee catalog entity | `stock.Coffee` typed dict (`hr_id`, `origin`, `varietals`, `stock`, etc.) | No direct `/aroast` request mapping; fetched via `/acoffees` | `stock['coffees'][]` | Stock cache is server-driven concept payload (`src/plus/stock.py:82-95`, `src/plus/stock.py:135-141`) | Optional fields (`total=False`) | High: schema drift in `coffees` breaks labels/selection | `grade` comment says “not transferred from server” (`src/plus/stock.py:87`) |
| GreenBean concept | Not a first-class local type in `plus`; implied via coffee inventory and backend references comment | none in roast summary | Possibly backend `green_bean_id` in references raw payload | References fallback implies backend can link references by `green_bean_id` instead of coffee/blend (`src/plus/stock.py:1822-1825`) | N/A | Medium: assumption mismatch can hide references | Mapping between Coffee and GreenBean is implicit, not explicit in client types |
| Lot concept | Not explicit as a top-level plus field; stock location + amount used | none | `location`/stock amounts and schedule location ids | Client uses `location_hr_id` and `location` as storage site; no explicit lot-id field in roast sync (`src/plus/stock.py:77-80`, `src/plus/roast.py:362-389`) | Optional in roast; required in schedule stock context | High if backend equates location with lot incorrectly | “Lot” may be backend warehouse concept not represented in `/aroast` sync |
| Inventory quantity | `StockItem.amount` (kg) | none on roast; schedule item uses `amount` batch size | `stock.coffees[].stock[].amount`, `schedule[].amount` | Units interpreted as kg in stock/schedule typed docs (`src/plus/stock.py:80`, `src/plus/stock.py:123`) | Required in schedule; optional in coffee stock item presence | High if unit basis changes | No SKU field observed in plus API models |
| SKU | none found in inspected plus models | none | none | No dedicated SKU key in `plus/stock.py`, `plus/roast.py`, `plus/sync.py` | N/A | Medium: downstream integrations expecting SKU cannot rely on client | SKU might exist only in backend `_raw` reference or other endpoints not inspected |

### 6.2 Blend, Batch, Roast core concepts

| Concept | Artisan/internal source field | Roastlocal Cloud request field | Roastlocal Cloud response field | Transformation / adaptation logic | Required vs optional | Risk if changed | Unclear assumptions |
|---|---|---|---|---|---|---|---|
| Blend attached to roast | `aw.qmc.plus_blend_spec` | `blend` object (trimmed) | `blend.label`, `blend.ingredients[].coffee.hr_id/label`, `ratio[_num/_denom]` | Outbound trims to `{label, ingredients[{coffee,ratio,ratio_num,ratio_denom}]}`; inbound reconstructs local spec and label list (`src/plus/roast.py:259-279`, `src/plus/roast.py:374-381`, `src/plus/sync.py:575-603`) | Optional; `None` sent to clear | High: ingredient shape differences break mapping | Blend and coffee are mutually exclusive in client logic |
| Batch identifiers | `roastbatchnr`, `roastbatchprefix`, `roastbatchpos` | `batch_number`, `batch_prefix`, `batch_pos` | same keys in roast response | Numeric/string range-limited and synced both directions (`src/plus/roast.py:45-53`, `src/plus/sync.py:506-531`) | Optional; default suppress/reconstruct | Medium-High | Batch semantics (production lot vs display id) not guaranteed identical |
| Roast identity | `roastUUID` (`config.uuid_tag`) | `roast_id` | `roast_id` or equivalent UUID in endpoint path | `id -> roast_id` normalization in getRoast (`src/plus/roast.py:140`, `src/plus/roast.py:296-300`) | Required for sync/update | Critical | UUID canonical form normalized by helper in some paths |
| Roast schedule link | `scheduleID`, `scheduleDate` | `s_item_id`, `s_item_date` | `s_item_id` only (date explicitly not returned) | Comment states server does not store/return `s_item_date` (`src/plus/roast.py:141-143`, `src/plus/sync.py:638-646`) | `s_item_id` optional but persisted in non-suppressed sync set | Medium | Server-side schedule date linkage may rely on other storage |
| Roast amount / weights | `weight[]`, `defects_weight` | `amount`, `end_weight`, `defects_weight` (kg) | same keys | Converts from local weight unit to kg both outbound and inbound (`src/plus/roast.py:68-127`, `src/plus/sync.py:472-505`) | `amount` always present; others optional with default 0/None semantics | High | `amount` means green input weight, not generic “batch size” in all contexts |

### 6.3 Roast profile, curves, controls, events

| Concept | Artisan/internal source field | Roastlocal Cloud request field | Roastlocal Cloud response field | Transformation / adaptation logic | Required vs optional | Risk if changed | Unclear assumptions |
|---|---|---|---|---|---|---|---|
| Phase events CHARGE/TP/DRY/FC/DROP | `computed.CHARGE_*`, `TP_*`, `DRY_*`, `FCs_*`, `FCe_*`, `DROP_*`; plus `timeindex/specialevents` in `.alog` | `charge_temp_ET`, `charge_temp`, `TP_temp`, `DRY_temp`, `FCs_temp`, `FCe_temp`, `drop_temp`, `drop_temp_ET`; times: `TP_time`, `DRY_time`, `FCs_time`, `FCe_time`, `drop_time` | same flat keys expected on fetch/apply subset | Extracted from computed metrics, not from raw event timeline arrays (`src/plus/roast.py:203-227`) | Optional (sent only if present/non-suppressed by helper constraints) | High | Client sends derived phase summary, not full event stream semantics |
| Roast curves (time-series arrays) | `.alog` arrays (`timex`, temp curves, extra curves) | Not in `/aroast` JSON summary; carried via profile file upload | Not reconstructed in `applyServerUpdates`; fetched as profile data only in separate workflow | Curves are primarily transported by `.alog` upload endpoint when enabled (`src/plus/config.py:209-225`, `src/plus/queue.py:531-571`) | Optional feature (depends on `profile_upload_enabled`) | High | Backend may parse full profile differently than summary fields |
| Gas/Airflow/Drum controls | `.alog` includes event types/values (`etypes`, `specialevents*`, e.g., Air/Drum/Burner in sample) | Not explicitly mapped into `/aroast` summary fields | Not explicitly mapped back by `applyServerUpdates` | Control timeline appears to live in full profile content; summary carries only derived metrics/notes (`src/test/sanity/data/artisan/profile1.json:1`, `src/plus/roast.py:285-428`) | Optional / indirect | High | Meaning of control events likely backend-specific if extracted from `.alog` |
| FC RoR reference metric | `computed.fcs_ror` | `FCs_RoR` | not explicitly applied inbound in sync layer | Converted using RoR temp conversion helper in template generation (`src/plus/roast.py:229-235`) | Optional | Medium | One-way usage in current sync subset |

### 6.4 Roast profile references

| Concept | Artisan/internal source field | Roastlocal Cloud request field | Roastlocal Cloud response field | Transformation / adaptation logic | Required vs optional | Risk if changed | Unclear assumptions |
|---|---|---|---|---|---|---|---|
| Reference profile list for coffee/blend/machine | selected coffee/blend/machine in UI context | query params: `coffee_hr_id`, `blend_hr_id`, `machine` to `/roasts/references` | response `data.items[]` normalized to `{uuid,label}` from `id` + `reference_name|title` | Fallback retry without coffee/blend filter when zero hits (comment: backend may link by `green_bean_id`) (`src/plus/stock.py:1805-1835`) | Optional | High | Clear evidence that Coffee term may not equal GreenBean linkage |

### 6.5 QC/cupping, colors, roast descriptors

| Concept | Artisan/internal source field | Roastlocal Cloud request field | Roastlocal Cloud response field | Transformation / adaptation logic | Required vs optional | Risk if changed | Unclear assumptions |
|---|---|---|---|---|---|---|---|
| Cupping notes | `cuppingnotes` | `cupping_notes` | `cupping_notes` | String-limited outbound; empty-string suppression to `None`; inbound reconstructs default empty string (`src/plus/roast.py:397`, `src/plus/sync.py:324-327`, `src/plus/sync.py:689-695`) | Optional | Medium | None |
| Cupping score | derived from `flavors` by `calcFlavorChartScoreFromFlavors` | `cupping_score` | `cupping_score` | default score `50` suppressed to `None`; inbound missing value restored to 50 (`src/plus/roast.py:402-408`, `src/plus/sync.py:321-323`, `src/plus/sync.py:696-703`) | Optional | Medium | Score origin (manual vs derived) may differ between clients |
| Roast notes | `roastingnotes` | `notes` | `notes` | standard string mapping with empty suppression (`src/plus/roast.py:392`, `src/plus/sync.py:682-688`) | Optional | Low-Medium | None |
| Color fields | `whole_color`, `ground_color`, `color_system` | same names | same names | zero/empty suppression and default reconstruction; unknown cloud color_system names can fail local index lookup (`src/plus/roast.py:179-184`, `src/plus/sync.py:648-674`) | Optional | Medium-High | Cross-system color taxonomy not guaranteed |

### 6.6 Sticker / print / export

| Concept | Artisan/internal source field | Roastlocal Cloud request field | Roastlocal Cloud response field | Transformation / adaptation logic | Required vs optional | Risk if changed | Unclear assumptions |
|---|---|---|---|---|---|---|---|
| Stickers / print metadata | Not found in inspected `plus` sync model | none | none | No dedicated fields in `plus.roast/sync/stock/config` for sticker/label print mapping | N/A | Medium (for business workflows expecting these fields) | Could exist in non-plus modules or backend-only representations |
| Export fields | Client has general export features, but no dedicated roast-sync export concept fields in `plus` data mapping | none | none | Export functionality is separate from cloud sync payload model | N/A | Low-Medium | If backend expects export metadata, current mapping evidence is insufficient |

## 7. Roastlocal Cloud assumptions

Facts from code comments/behavior:

- Backend suppresses null/default sync values and client reconstructs them (`src/plus/sync.py:444-465`).
- Backend does not return all sent attributes (`unsynced` one-way attributes), including several computed/environmental values (`src/plus/roast.py:451-482`, `src/plus/sync.py:718-722`).
- Backend may resolve references by GreenBean-like linkage (`green_bean_id`) even when client asks by coffee/blend (`src/plus/stock.py:1822-1825`).

Inference:

- Roastlocal Cloud appears to implement a compatibility facade where “coffee” in roast context can map to a different warehouse model identity.

## 8. Artisan compatibility assumptions

- Client intentionally keeps compatibility behavior where explicit `None` must be sent for `coffee/blend/location` cleanup (`src/plus/roast.py:369-381`, `src/plus/roast.py:383-389`).
- Summary roast JSON and full `.alog` transfer are independent channels and must both remain compatible (`src/plus/queue.py:531-571`, `src/plus/queue.py:635-641`).
- Batch and cupping default suppression logic is part of sync identity, not just optimization (`src/plus/sync.py:317-397`).

## 9. Conflicts and contradictions

1. **Concept naming conflict:** client uses `coffee` in roast payload, while reference-fetch fallback explicitly states backend linkage may be via `green_bean_id`.
2. **Schedule date contradiction:** client sends `s_item_date` but comments indicate server does not store/return it (`src/plus/sync.py:638-646`).
3. **Scope mismatch:** raw `.alog` includes rich control/event/curve data, but `/aroast` summary mapping includes only derived phase and metadata keys.

## 10. Risks

- Breaking coffee/greenbean semantic bridge can silently remove reference matches and profile suggestions.
- Changing default suppression behavior (`0/50/'' <-> None`) can create false diffs, stale values, or failed field cleanup.
- Treating location as lot (or vice versa) without explicit mapping can corrupt inventory/accounting semantics.
- Assuming `/aroast` alone contains full roast intent ignores control/event/curve detail carried by profile upload.

## 11. What must not be broken

- `roastUUID -> roast_id` identity continuity and sync cache semantics.
- Explicit cleanup semantics for `coffee`, `blend`, `location` via `None`.
- Weight unit conversion to/from kg for `amount`, `end_weight`, `defects_weight`.
- Phase event summary mapping (`CHARGE/TP/DRY/FC/DROP`) from computed values.
- Reference lookup fallback behavior when coffee/blend-filtered query returns zero results.
- Dual-channel upload behavior: roast summary (`/aroast`) and full profile (`/upload-profile`).

## 12. Owner questions

1. In Roastlocal Cloud domain terms, what is the authoritative distinction and mapping rule between `coffee_hr_id` and backend `green_bean_id`?
2. Is `location` in roast payload intended as storage site, lot identifier, or both (context-dependent)?
3. Should `s_item_date` be persisted server-side, or should client stop sending it to avoid misleading assumptions?
4. For production-critical analytics, should controls/events/curves be considered authoritative only from full profile upload, or should part of them be normalized into `/aroast` JSON?
5. Is there a planned explicit SKU/lot field in the compatibility contract, or should current workflows continue using inferred mappings from coffee/location?

## 13. Suggested next investigation

Run a narrow contract archaeology on `/roasts/references` and `/aroast` backend schemas (request/response examples) to formalize a canonical **Coffee vs GreenBean vs Lot** glossary and machine-readable mapping table for both client and cloud teams.
