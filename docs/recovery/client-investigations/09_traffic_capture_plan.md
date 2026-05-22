# Client Investigation: Traffic capture plan to validate modified Artisan client against local Roastlocal Cloud backend

## 1. Research question

What traffic capture plan should be used to validate the modified Artisan client against a local Roastlocal Cloud backend running on the same computer?

## 2. Executive summary

A reliable validation capture must focus on loopback traffic and a strict UI-action script, because both client and backend run locally. The plan should capture only traffic needed to validate known integration contracts from earlier investigations (`02`, `03`, `05`), avoid secret leakage, and produce a sanitized evidence report instead of raw packet artifacts in git.

The recommended approach is:
- capture loopback interface by OS,
- scope traffic to backend/frontend localhost ports,
- execute a deterministic UI checklist with timestamps,
- correlate each UI action to expected endpoint calls,
- export only sanitized markdown findings,
- compare observed behavior to the expected contract matrix from reports `02`, `03`, `05` and cloud API reports.

## 3. Files inspected

- `docs/recovery/client-investigations/02_cloud_integration_boundary.md`
- `docs/recovery/client-investigations/03_http_network_layer.md`
- `docs/recovery/client-investigations/05_sync_import_export_workflows.md`
- `src/plus/config.py`
- `src/plus/connection.py`
- `src/plus/queue.py`
- `src/plus/sync.py`
- `src/plus/stock.py`
- `src/plus/schedule.py`
- `src/plus/notifications.py`

## 4. Facts from code

- Client traffic is driven through `requests` wrappers in `src/plus/connection.py` (`getData`, `sendData`, `sendFile`).
- Base endpoints are assembled in `src/plus/config.py` and include:
  - `/accounts/users/authenticate`
  - `/acoffees`
  - `/aroast`
  - `/aschedule/lock`
  - `/notifications`
  - `/roasts/{roast_id}/upload-profile`
  - `/roasts/{roast_id}/profile/data`
  - `/roasts/references`
- Request behaviors relevant for packet interpretation:
  - bearer auth header,
  - JSON POST/PUT,
  - optional gzip body compression for larger payloads,
  - multipart profile upload,
  - `modified_at` and date query usage.
- Prior investigations already identify expected endpoint semantics (`200/204/401/404/409` handling in key flows).

## 5. Network/API behavior

### 5.1 Capture objective

Validate that UI workflows produce the expected HTTP method/path/status/shape patterns against local backend compatibility routes.

### 5.2 Interface selection by OS

- macOS:
  - Capture interface: `lo0` (loopback).
  - Reason: `localhost` traffic does not traverse Wi-Fi/Ethernet interfaces.
- Linux:
  - Preferred: `lo`.
  - Optional fallback: `any` if loopback visibility is inconsistent in local setup.
- Windows:
  - Capture adapter: `Npcap Loopback Adapter`.
  - Reason: localhost traffic is visible there with Npcap.

### 5.3 Capture filters (BPF)

Assuming backend at `localhost:8000` and possible frontend at `localhost:5173`:

- Backend-only (recommended default):
  - `host 127.0.0.1 and tcp port 8000`
- Backend + frontend correlation view:
  - `(host 127.0.0.1) and (tcp port 8000 or tcp port 5173)`
- If IPv6 localhost is used:
  - `(host 127.0.0.1 or host ::1) and (tcp port 8000 or tcp port 5173)`

Notes:
- Start with backend-only filter to reduce noise.
- Expand to include frontend only when UI->frontend->backend timing correlation is needed.

### 5.4 Display filters (Wireshark/tshark analysis)

Use display filters after capture to inspect specific concerns:

- Local backend HTTP traffic:
  - `http and tcp.port == 8000`
- Auth endpoint:
  - `http.request.uri contains "/accounts/users/authenticate"`
- Roast upload/update path:
  - `http.request.uri contains "/aroast"`
- Stock/schedule pull:
  - `http.request.uri contains "/acoffees" or http.request.uri contains "/aschedule/lock"`
- Notifications:
  - `http.request.uri contains "/notifications"`
- Profile file upload:
  - `http.request.uri contains "/upload-profile"`
- References/profile data:
  - `http.request.uri contains "/roasts/references" or http.request.uri contains "/profile/data"`
- Error/status spotlight:
  - `http.response.code >= 400`

### 5.5 Suggested tshark command patterns

Examples (do not commit output files):

- List interfaces first:
  - `tshark -D`
- Capture backend localhost on macOS/Linux loopback:
  - `tshark -i lo0 -f "host 127.0.0.1 and tcp port 8000" -w /private/tmp/ra09_backend_capture.pcapng`
- Linux variant:
  - `tshark -i lo -f "host 127.0.0.1 and tcp port 8000" -w /tmp/ra09_backend_capture.pcapng`

Uncertainty:
- Exact interface label can vary by host and driver setup; always verify with `tshark -D` before capture.

## 6. Data model mapping

Use the following mapping during analysis to tie observed traffic to client intent:

| UI/Workflow action | Expected method/path family | Key expected request traits | Key expected response traits |
|---|---|---|---|
| Login/connect | `POST /accounts/users/authenticate` | JSON credentials payload | auth envelope with token or auth failure |
| Stock/schedule refresh | `GET /acoffees` | `today`, optional `lsrt` query | `200` with payload or `204` no-content |
| Roast save/sync | `POST /aroast` | JSON roast/sync fields, possible idempotency key | success/validation/conflict behavior |
| Schedule lock | `POST /aschedule/lock` | date query | lock acknowledgment status |
| Notification poll | `GET /notifications` | optional machine query | list payload or empty |
| Full profile upload | `POST /roasts/{id}/upload-profile` | multipart file field | upload success/failure code |
| Sync freshness check | `GET /aroast/{uuid}` | optional `modified_at` query | `200` updated data, `204` no newer, `404` missing |
| Reference lookup | `GET /roasts/references` | filter queries (coffee/blend/machine) | `data.items`-style list |

## 7. Roastlocal Cloud assumptions

Facts from current repo assumptions:
- Local backend compatibility is expected on Plus-style routes under local host/port.
- Endpoint/path and status behavior should remain compatible with client expectations documented in investigations `02`, `03`, `05`.

Inference:
- Traffic validation should prioritize behavioral parity over internal backend implementation details.

## 8. Artisan compatibility assumptions

- Client behavior intentionally includes retries/re-auth and sometimes decoupled workflows (e.g., roast summary and profile upload).
- A valid capture plan must include flows that can produce `204`, `401`, `404`, or retry patterns, not only happy-path `200`.

## 9. Conflicts and contradictions

Potential contradiction to watch during capture analysis:
- If backend returns route/status/payload forms that differ from earlier assumptions (e.g., different envelope fields, unexpected status for `modified_at` checks), log as explicit contract drift rather than silently accepting it.

## 10. Risks

- Capturing wrong interface (not loopback) leading to false conclusion of “no traffic”.
- Overly broad capture producing sensitive raw data and noisy analysis.
- Missing UI-action timestamps causing weak request-to-action attribution.
- Assuming TLS/plain HTTP format without verifying local deployment settings.
- Committing raw `.pcap/.pcapng` or leaking tokens/cookies in notes.

## 11. What must not be broken

- Existing Artisan client compatibility paths against local Roastlocal backend routes.
- Authentication/session and sync semantics expected by current client.
- Queue/retry/profile-upload bridge behavior used in production-like workflows.
- Security hygiene: no secrets or raw captures in repository commits.

## 12. Owner questions

1. Which exact local backend bind is active in current run: `127.0.0.1:8000`, `0.0.0.0:8000`, or another host/port?
2. Is local API plain HTTP or HTTPS (self-signed certificate)?
3. Should validation include a forced auth-expiry scenario to explicitly observe `401 -> re-auth -> retry` sequence?
4. Is profile upload path (`/roasts/{id}/upload-profile`) required in this validation pass, or optional?
5. Which cloud API report is the source of truth when current client-code assumptions and external docs differ?

## 13. Suggested next investigation

Run a single-session pilot capture using the checklist below, then produce a sanitized mismatch matrix (expected vs observed) specifically for login, stock fetch, roast upload, sync update fetch, and profile upload.

## Traffic capture execution checklist (recommended)

1. Pre-check environment
- Confirm backend container is up and reachable on expected localhost port.
- Confirm modified Artisan client points to local backend URL.
- Confirm system time is synced.

2. Start capture on loopback adapter
- Use OS-specific interface from section 5.2.
- Apply backend-focused capture filter.

3. Execute deterministic UI actions with manual timestamp log
- Keep a simple action log: `HH:MM:SS | UI action | expected endpoint(s)`.

4. Stop capture immediately after checklist
- Save raw file to temporary local path outside repo.

5. Analyze with display filters
- Extract only method/path/status/field-name-level findings.

6. Write sanitized summary markdown
- Save under `docs/recovery/client-investigations/`.
- Do not include secrets or raw payload values.

## Recommended UI action checklist for correlation

Use in order, one action at a time, waiting for each network burst to complete:

1. Launch client and open login/connect dialog.
2. Perform login/connect to local backend.
3. Trigger stock/schedule refresh.
4. Open a prepared roast or create/select a roast for sync.
5. Save/update roast properties (to trigger `/aroast`).
6. Trigger a sync/freshness check action if available.
7. Trigger schedule lock-related action if workflow uses it.
8. Trigger notification retrieval path (manual refresh if available).
9. Trigger references lookup flow (coffee/blend/machine dependent UI).
10. If enabled, trigger full profile upload workflow.
11. If available, trigger remote profile data fetch workflow.
12. Logout/disconnect and reconnect once (optional resilience check).

## What not to capture

- Do not capture non-local unrelated interfaces unless needed.
- Do not capture long background sessions with unrelated user activity.
- Do not capture and commit raw packet artifacts (`.pcap`, `.pcapng`, raw exports).
- Do not include credentials, bearer tokens, cookies, API keys, or customer-identifying values in any report.

## Sanitization rules for findings

Allowed in report:
- timestamp,
- UI action label,
- HTTP method,
- URL path (without secret query values),
- status code,
- field names only (not sensitive values),
- high-level payload shape,
- normalized error message text without secrets.

Required redaction examples:
- `Authorization: Bearer <REDACTED_TOKEN>`
- `Cookie: <REDACTED_COOKIE>`
- `email/password -> <REDACTED_CREDENTIALS>`
- UUIDs or IDs tied to real customers -> masked where needed.

## Traffic summary document template (sanitized)

Suggested filename pattern:
- `docs/recovery/client-investigations/09a_traffic_capture_summary_<YYYYMMDD>.md`

Suggested sections:
- Scope/session metadata (host OS, interface, capture filter, client/backend version refs)
- UI action timeline
- Observed requests table
- Status code matrix
- Endpoint compatibility notes
- Mismatches vs expected contract
- Risks observed
- Open questions

Suggested observed requests table columns:
- `Time`
- `UI Action`
- `Method`
- `Path`
- `Status`
- `Request Fields (names only)`
- `Response Fields (names only)`
- `Notes`

## How to compare captured traffic with reports 02/03/05 and cloud API reports

Comparison procedure:

1. Build expected baseline from existing investigations:
- `02`: integration boundary and endpoint inventory.
- `03`: transport/auth/headers/retry/status semantics.
- `05`: sync/import/export workflow sequencing.

2. Build observed set from sanitized traffic summary:
- unique method/path pairs,
- per-path status outcomes,
- key request/response field-name envelopes.

3. Produce a three-way matrix per endpoint/workflow:
- `Expected from client code/reports`
- `Observed in capture`
- `Declared in cloud API reports`

4. Classify each row:
- `Match`
- `Partial match`
- `Mismatch`
- `Not exercised`

5. For each mismatch, label source type:
- client assumption issue,
- backend contract drift,
- environment/config issue,
- insufficient evidence.

6. Escalate only compatibility-relevant deltas:
- Any change that could break current Artisan client behavior should be marked as high-priority compatibility risk.
