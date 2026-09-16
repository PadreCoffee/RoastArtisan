# Roest firmware → Artisan native integration — implementation report & events handoff

_2026-09-06 · branch `feat/roest-native-device` (unmerged, base `__version__` 1.0.5) · reference firmware/bridge repo: `~/Desktop/RoestFirmwareUPD/roest-bridge/` (`roest_record.py`, `roest_control.py`, `usb_bridge.py`)._

Purpose: document what is **already built and bench-verified** (telemetry + control) so the events
work (auto-detect + marking) is finished **in the same architecture as the control path**.

---

## 1. Architecture

Native USB device, **Path B**: `Roest (patched firmware) --USB CDC serial--> Artisan`. No external
bridge, no WebSocket, no Modbus. Artisan opens `/dev/tty.usbmodem*` directly (exclusive) and both
reads telemetry and writes control frames on the **same** port (mirrors `usb_bridge.py`, which used
one `serial.Serial` for read+write).

The codec is **ported verbatim** from `roest-bridge` — do not re-reverse-engineer; reuse it.
`artisanlib/roest_device.py` = decode/frame + `class Roest(AsyncComm)`.

Bench status (2026-09-06): **telemetry works, control works** (drum/fan/power move the roaster over
USB). Events are the only remaining piece.

---

## 2. Telemetry — 22-byte record (verbatim, byte extraction is correct)

Frame on wire: `A5 5A | 22 record bytes | 1 XOR`. Decode `artisanlib/roest_device.py:40-57`
(identical to `roest_record.py`):

| offset | field | meaning |
|--------|-------|---------|
| 0x00 u16 | bt | °C×100 (0xFFFF→None) |
| 0x02 u16 | et | °C×100 |
| 0x04 u16 | rtd2 | °C×100 |
| 0x06 u16 | rtd3 | °C×100 |
| 0x08 u16 | drum_temp | °C×100 |
| 0x0A u16 | inlet_temp | °C×100 |
| 0x0C u16 | target | °C×100 |
| 0x0E u8 | pcb_temperature | °C |
| 0x10 u16 | t_state | `msec=(v&0x1FFF)*1000`, **`phase=(v>>14)&3`** |
| 0x12 u32 | packed | **`crack=v&0xFF`**, `heat=((v>>8)&0x3FF)/10`, `rpm=(v>>18)&0x7F`, `fan=(v>>25)&0x7F` |

**Firmware update (events chat, 2026-09-06):** the patched firmware now appends a **23rd byte
`state0`** (`*(0x20000fb8)` low byte — the main roast FSM). Wire frame is now
`A5 5A | 22 record bytes | 1 state0 byte | XOR(23)` = 26 bytes; XOR covers all 23 payload bytes.
`state0` is the bench-confirmed auto-detect source and **supersedes `phase`/`crack`** for events
(both were rejected on the bench — see §6a). Existing 22-byte field extraction is unchanged; read
`state0 = payload[22]`. Spec: `~/Desktop/RoestFirmwareUPD/roest-bridge/docs/2026-09-06-roest-events-exact-enum-spec.md`.

---

## 3. Device wiring (Artisan side, branch)

Device ids and their readers (`artisanlib/comm.py`; names `artisanlib/canvas.py:1001-1004`):

| id | dropdown name | reader (`comm.py`) | returns (t1, t2) |
|----|---------------|--------------------|------------------|
| 201 | Roest BT/ET (main meter) | `Roest_BTET` (`comm.py:2076`) | (getET, getBT) |
| 202 | +Roest Heat/Fan | `Roest_HF` (`comm.py:2088`) | (getHeat=heat-field, getFan=fan-field) |
| 203 | +Roest RPM/Drum | `Roest_RD` (`comm.py:2097`) | (getRPM=rpm-field, getDrumTemp=drum_temp) |
| 204 | +Roest Inlet/Target | `Roest_IT` (`comm.py:2108`) | (getInletTemp, getTarget) |

Connect (device==201): `canvas.py:13466-13490` — auto-globs `/dev/tty.usbmodem*` if `aw.ser.comport`
is unset, builds `SerialSettings` (115200 8N1), `Roest(...).start()`. Disconnect: `canvas.py:13681`.
Artisan maps extra readers positionally: `t1→extratemp1→extraname1`, `t2→extratemp2→extraname2`
(`canvas.py:19771-19775`) — **no reversal**.

---

## 4. ⚠️ Bench-verified channel mapping (the firmware field NAMES are not all physically accurate)

Byte extraction is correct, but several firmware field *names* do NOT match the roaster's real
channels. The owner verified the true mapping on the bench and saved it in his working config
`~/Desktop/roest artisan integr.aset`. **That .aset is the source of truth for labels.** Verbatim:

```
[Device] id=201
[ExtraDev]
extradevices     = 202, 203, 204, 25
extraname1       = Air,   DrumT, Target, "Target DTR"
extraname2       = Power, Rpm,   Inlet,  "Extra 2"
extradevicecolor1= #f34042ff, #194516ff, #a12ab5ff, #000000
extradevicecolor2= #1650fcff, #1a4310ff, black,     #000000
```

So the real display mapping (reader field → verified label) is:

| device | extratemp1 (t1) field | verified label | extratemp2 (t2) field | verified label |
|--------|------------------------|----------------|------------------------|----------------|
| 202 | heat-field | **Air** | fan-field | **Power** |
| 203 | rpm-field | **DrumT** | drum_temp-field | **Rpm** |
| 204 | inlet_temp-field | **Target** | target-field | **Inlet** |

(device 25 = a virtual/symbolic extra the owner added: `Target DTR` / `Extra 2`.)

Implication for a clean release: either bake these labels into a **machine preset** (recommended — one
click) or rename the getters/device names in code to match. Until then, the labels live in the .aset.
The control channel names (§5) are separate and correct as-is.

---

## 5. Control — IMPLEMENTED (this is the pattern events must follow)

End-to-end chain for a control command:

1. Artisan slider/button, action type **IO Command** (`action==6`; NOT "Artisan Command" which is 20).
2. command string `roest(<chan>,<value>)` (slider substitutes `{}` → value, `main.py:8872`).
3. eventaction handler `main.py:9714` (`c.startswith('roest')`) →
4. `_parse_roest_command(c)` `main.py:1436` — accepts only `drum`/`fan`/`power`, returns `(chan,value)`; anything else → None (ignored) →
5. `roestSendMessageSignal.emit(chan,value)` `main.py:9718` (signal `main.py:1496`, connected `main.py:4376`) →
6. slot `roestSendMessage` `main.py:18216` → `self.roest.send_msg(chan,value)` →
7. `Roest.send_msg` `roest_device.py:225` → `encode`/`encode_power` → `self.send(frame * CTRL_REPEAT)` (8× burst) over the USB serial.

Channels (`roest_device.py:87-88`): `drum` 0x44 int 20-65, `fan` 0x46 int 30-100, `power` 0x50 float
0-100. Frames: `5A A5 <chan> <val> <xor>` (drum/fan) / `5A A5 'P' <f32LE> <xor>` (power). Device
clamps again.

Owner's working slider config (from the .aset), all **IO Command** (`slideractions=11`):

```
slidercommands = "roest(fan,{})", "roest(drum,{})", , "roest(power,{})"
slidermin      = 30, 30, 0, 0
slidermax      = 100, 60, 100, 100
```

---

## 6. Events — TO DO (finish in the same architecture)

Two independent directions.

### 6a. Roaster → Artisan (auto-detect) — SPEC READY (via `state0`), firmware done & bench-confirmed

Source is the new 23rd telemetry byte **`state0`** (roast FSM), NOT phase/crack. Bench-rejected
alternatives: `phase` (only idle/active), the `event_record` enum (dominated by internal event 10 —
useless, and its call caused the motor-stuck fault), `crack` (FC-only). `state0` tracked a full
charge→yellow→crack→drop sequence exactly.

`state0` → mark map (fire on rising edge INTO the value: `prev != cur && cur == V`):

| state0 | event | Artisan mark |
|--------|-------|--------------|
| 5 | CHARGE | `markCharge` |
| 6 | DRY / yellowing | `markDryEnd` |
| 7 | FIRST CRACK | `mark1Cstart` |
| 9 | DROP (→10→4→1) | `markDrop` — robust: fire when state0 **leaves 7** (`prev==7 && cur∈{9,10,4,1}`) in case 9 is dropped by a slow USB read |

The Artisan firing structure already exists and is **dormant**:
- Stubs `roest_device.py:167-178` (`_is_charge/_is_dry/_is_fcs/_is_drop`, all `return False`).
- `register_reading` `roest_device.py:180-205` edge-detects and calls the handlers (keep it; compare new
  `state0` to prev).
- Handlers wired at connect `canvas.py:13485-13488`, gated by `aw.roestEventFlags[i]` + a timeindex
  guard → `markChargeDelaySignal(0)` / `markDRYSignal` / `markFCsSignal` / `markDropSignal`
  (→ `markChargeDelay`/`markDryEnd`/`mark1Cstart`/`markDrop`, `canvas.py:2591-2599`).
- `roestEventFlags` = 7 bools [CHARGE, DRY, FCs, FCe, SCs, SCe, DROP], default all False, `main.py:1887`.

**Work to finish 6a (branch):**
1. **Frame length 22→23**: in `deframe`/`read_msg` (`roest_device.py:60-83, 208-223`) read one extra
   byte, XOR over 23; `decode_record` returns `state0 = payload[22]`. Existing 22-byte extraction
   unchanged.
2. Fill the four stubs from `state0` (entered 5 / 6 / 7 / left 7). Delete the phase/crack + event-enum
   TODOs and the dormant-proof test.
3. Enable `roestEventFlags` (default CHARGE/DRY/FCs/DROP True, or add Device-dialog checkboxes) so the
   handlers fire. Keep the timeindex guards (no double-mark).
4. Verify with `roest-bridge/verify_usb.py` (prints `state0=N(NAME)` live) against the app.

### 6b. Artisan → Roaster (manual marking) — PARKED (P4)

Superseded/de-scoped vs the earlier plan: the reference `encode_event` (chan `'E'` 0x45, via the
firmware `event_record`) is exactly what caused the **motor-stuck fault** — do NOT wire it. Owner's
decision: only **DROP** is a meaningful roaster action, and it must go through a **non-blocking native
dropper trigger** (dropper state machine `0x080b21c4`), not `event_record`. That needs firmware RE + a
careful bench pass → **parked P4**. The old WebSocket `send({"command":"markEvent",...})` buttons do
nothing on native USB; leave manual-mark-to-roaster out until P4 is done. (Control drum/fan/power in §5
is unaffected.)

---

## 7. File index (branch `feat/roest-native-device`)

- Codec/device: `src/artisanlib/roest_device.py` (decode 40-57, CHAN/encode 87-111, getters 145-152,
  stubs 167-178, register_reading 180-205, send_msg 225-230).
- Readers: `src/artisanlib/comm.py:2076-2112`; devicefunctionlist `:579-582`.
- Names/connect/disconnect/handlers: `src/artisanlib/canvas.py:1001-1004, 13466-13490, 13681-13683, 13485-13488, 2591-2599`.
- Control + events glue: `src/artisanlib/main.py` (`_parse_roest_command` 1436, signal 1496, connect 4376,
  eventaction branch 9714, slot 18216, roestEventFlags 1887; slider substitution 8872, IO Command 9495).
- Reference (do not re-derive): `~/Desktop/RoestFirmwareUPD/roest-bridge/roest_control.py`, `roest_record.py`, `usb_bridge.py`.
- Owner's verified config: `~/Desktop/roest artisan integr.aset`.
- Existing plan/ledger: `docs/superpowers/plans/2026-09-04-roest-native-device.md`, `.superpowers/sdd/2026-09-04-roest-native-device/`.

---

## 8. TL;DR for the events chat

Telemetry + control (drum/fan/power via **IO Command** `roest(chan,{})`) are done and bench-verified.
Events: **6a (auto-detect) is spec-ready via the new 23rd byte `state0`** — extend the frame 22→23,
fill the four dormant `_is_*` stubs from `state0` (entered 5/6/7, left 7), and expose `roestEventFlags`
so auto-marking fires; verify with `verify_usb.py`. **6b (manual mark-to-roaster) is parked P4** —
`event_record` is the motor-stuck path, so only DROP via a future non-blocking dropper trigger, after
firmware RE. Labels/colours/sliders are captured in the owner's `.aset` (bench-verified §4).
