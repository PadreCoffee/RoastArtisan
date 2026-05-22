# Client Investigation 10 — Traffic Analysis

## 1. Research question

What does the captured traffic reveal about the actual modified Artisan client ↔ Roastlocal Cloud behavior?

## 2. Executive summary

The capture confirms live use of core compatibility endpoints (`authenticate`, `acoffees`, `roasts/references`, `aroast`, profile upload/profile data) with mostly `200 OK` responses and one explicit `401 Unauthorized` login failure. Request ordering strongly matches expected UI-driven cloud workflows from investigations 02/03/05/06.

## 3. Inputs used

- `docs/recovery/client-investigations/traffic/traffic_summary_artisan_client.md`
- `docs/recovery/client-investigations/traffic/http_requests_sanitized.tsv`
- `docs/recovery/client-investigations/traffic/http_responses_sanitized.tsv`
- `docs/recovery/client-investigations/traffic/http_errors_sanitized.tsv`
- `docs/recovery/client-investigations/02_cloud_integration_boundary.md`
- `docs/recovery/client-investigations/03_http_network_layer.md`
- `docs/recovery/client-investigations/05_sync_import_export_workflows.md`
- `docs/recovery/client-investigations/06_ui_actions_cloud_calls.md`

## 4. Actual endpoints observed

- `GET /api/v1/acoffees`
- `GET /api/v1/aroast/{uuid}`
- `GET /api/v1/roasts/references`
- `GET /api/v1/roasts/{id}/profile/data`
- `POST /api/v1/accounts/users/authenticate`
- `POST /api/v1/aroast`
- `POST /api/v1/roasts/{id}/upload-profile`

## 5. Actual request order

Observed sequence pattern (sanitized):
1. `POST /accounts/users/authenticate`
2. `GET /acoffees`
3. Bursts of `GET /roasts/references` interleaved with occasional `GET /acoffees`
4. `GET /roasts/{id}/profile/data`
5. `GET /aroast/{uuid}`
6. `POST /aroast`
7. `POST /roasts/{id}/upload-profile`
8. Final login attempt `POST /accounts/users/authenticate` resulting in `401`

## 6. Status codes and errors

- Predominant status: `200 OK` across endpoint families.
- Error observed: `401 Unauthorized` on an authentication request (likely wrong-password attempt, inferred).
- No 5xx server errors observed in this capture.

## 7. Inferred scenario mapping

- wrong password login: observed (`401` on `authenticate`), confidence **high**.
- successful login: observed (`200` on `authenticate` earlier), confidence **high**.
- selecting different beans/coffees: inferred from repeated `acoffees` + `references` filtering calls, confidence **medium**.
- selecting reference: strongly indicated by repeated `references` calls and profile-data fetch, confidence **high**.
- uploading profile to cloud: observed `POST /roasts/{id}/upload-profile` with `200`, confidence **high**.

## 8. Expected calls that appeared in traffic

- `/api/v1/accounts/users/authenticate`
- `/api/v1/acoffees`
- `/api/v1/aroast`
- `/api/v1/aroast/{uuid}`
- `/api/v1/roasts/references`
- `/api/v1/roasts/{id}/profile/data`
- `/api/v1/roasts/{id}/upload-profile`

## 9. Expected calls not observed

- `/api/v1/aschedule/lock`
- `/api/v1/notifications`
- Note: absence in this capture does not prove endpoint is unused globally; it may be scenario-dependent.

## 10. Calls observed in traffic but missing from code investigations

- None identified; observed routes align with previously documented integration surfaces.

## 11. Backend routes that must remain stable

- `/api/v1/accounts/users/authenticate`
- `/api/v1/acoffees`
- `/api/v1/roasts/references`
- `/api/v1/aroast`
- `/api/v1/roasts/{id}/upload-profile`
- `/api/v1/roasts/{id}/profile/data`
- `/api/v1/aroast/{uuid}`

## 12. Compatibility risks

- High frequency of `roasts/references` calls means latency or contract drift here will visibly impact UI workflows.
- `401` handling depends on predictable auth contract and retry behavior; auth payload/status changes may break reconnect logic.
- Split upload flow (`POST /aroast` + `POST /upload-profile`) can produce partial cloud state if second phase fails.

## 13. Gaps / uncertainties

- This report intentionally excludes raw bodies and secrets; field-level payload conformance is not validated here.
- UI event labels are inferred from endpoint order and prior reports, not from direct UI telemetry in pcap.
- Capture is from localhost:8000 environment; production network topology may differ.

## 14. Owner questions

1. Should Investigation 11 validate payload field contracts for `/aroast` and `/upload-profile` using controlled synthetic fixtures?
2. Is repeated `/roasts/references` polling expected behavior for current UX, or should rate/trigger policy be reviewed?
3. For auth failures, do you want explicit UI differentiation between wrong password and other `401` causes?

## 15. Recommended input for investigation 11

- Sanitized endpoint sequence from this capture (`traffic_summary_artisan_client.md`).
- A controlled capture with one known scenario per workflow (login fail/success, bean switch, reference selection, upload).
- Backend-side route contract samples (status + key field names only, no sensitive values).
