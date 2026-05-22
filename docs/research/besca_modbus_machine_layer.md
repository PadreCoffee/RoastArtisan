# Besca Modbus Machine Layer — Research

## Executive summary

Artisan contains 6 Besca machine presets spanning two distinct firmware generations and two machine families (BSC and Bee). All presets use Modbus RTU serial (`type=0`), single device ID `1` on the primary bus (with one exception in the oldest preset). The read path uses holding registers (FC3) or input registers (FC4) depending on firmware version; the write path is concentrated in two address spaces: holding registers `1000–1010` for actuator state and coils `2003–2009` for relay/PID control.

The most information-rich preset is `BSC_full_automatic.aset`, which exposes button labels for every command and confirms the semantic meaning of the primary actuators. Combined with `BSC_automatic.aset` (the closest to the user's current setup), the register/coil map is largely decipherable without a machine present.

**Confidence levels:** High for registers 6/7 (BT/ET) and coils 2003–2006/2009 semantics via button labels. Medium for the value encoding scheme (2=start, 5=stop) and slider output ranges. Low for registers 1000/1002 (paired writes, unclear sub-role) and register 3904 (no label).

---

## Sources

| File | Description |
|------|-------------|
| `src/includes/Machines/Besca/BSC_automatic.aset` | Main auto preset, 115200 baud |
| `src/includes/Machines/Besca/BSC_full_automatic.aset` | Extended auto preset, most complete labels |
| `src/includes/Machines/Besca/BSC_manual_v1.aset` | Oldest manual preset, 9600 baud, two device IDs |
| `src/includes/Machines/Besca/BSC_manual_v2.aset` | Updated manual preset, different registers |
| `src/includes/Machines/Besca/Bee.aset` | Bee machine, 9600 baud |
| `src/includes/Machines/Besca/Bee_v2.aset` | Bee machine updated |
| `src/artisanlib/modbusport.py` | Artisan Modbus RTU backend |

---

## Transport configuration

### Comparison across all presets

| Preset | type | baudrate | parity | stopbits | timeout | comport (default) |
|--------|------|----------|--------|----------|---------|-------------------|
| BSC_automatic | 0 (RTU) | 115200 | N | 1 | 0.4s | COM5 |
| BSC_full_automatic | 0 (RTU) | 115200 | N | 1 | 0.4s | COM5 |
| BSC_manual_v1 | 0 (RTU) | 9600 | N | 1 | 0.4s | COM4 |
| BSC_manual_v2 | 0 (RTU) | 9600 | N | 1 | 0.4s | COM4 |
| Bee | 0 (RTU) | 9600 | N | 1 | 0.4s | COM4 |
| Bee_v2 | 0 (RTU) | 9600 | N | 1 | 0.4s | COM4 |

All presets also include `host=10.0.0.9, port=502` but this is unused for `type=0` (RTU serial).

**Conclusion:** Two firmware generations exist — **9600 baud** (older) and **115200 baud** (newer automatic). The user's machine uses 115200 baud based on their plist. COM port is always user-overridden at setup time.

---

## Read path — channel mapping

### BSC_automatic / BSC_full_automatic (115200 baud — current firmware)

| Channel | Register | FC | DeviceId | Div | Mode | Decoded channel |
|---------|----------|----|----------|-----|------|-----------------|
| input1 | 6 | 3 | 1 | 1 (÷10) | C | BT — bean temperature |
| input2 | 7 | 3 | 1 | 1 (÷10) | C | ET — exhaust/environment temp |
| input3–8 | — | — | 0 (inactive) | — | — | Not configured |

User's live plist adds `input3: reg=10, FC3, deviceId=1, div=1 (÷10)` — extra channel, semantic unknown.

### BSC_manual_v2 / Bee_v2 (9600 baud)

| Channel | Register | FC | DeviceId | Div |
|---------|----------|----|----------|-----|
| input1 | 45 | 3 | 1 | 1 (÷10) |
| input2 | 46 | 3 | 1 | 1 (÷10) |

### Bee / BSC_manual_v1 (9600 baud, oldest)

| Channel | Register | FC | DeviceId | Div | Notes |
|---------|----------|----|----------|-----|-------|
| input1 | 0 | 4 | 1 | 1 (÷10) | FC4 = input registers |
| input2 | 10 (Bee) / 0 (v1) | 4 | 1 / **2** | 1 (÷10) | BSC_manual_v1 uses deviceId=2 for ET — only preset with two device IDs |

**Scaling rule (confirmed):** All read values are raw integer tenths of °C. `raw ÷ 10 = °C`. Example: raw `2134` → `213.4°C`.

**Firmware split:** registers 6/7 (FC3) vs 45/46 (FC3) vs 0/10 (FC4) likely reflect three distinct Besca firmware versions. The user is on the 6/7/FC3 path.

---

## Write path — complete register/coil map

### Holding register writes (`writeSingle`)

#### Register 1000–1010 range — actuator state

Pattern observed across all write commands: values `2` and `5` appear exclusively. No intermediate values are ever written. This strongly suggests a state enum, not a continuous value.

**Inferred encoding:** `2` = start/open/on state, `5` = stop/close/off state.
This matches the button label pairs "↑1" (on) → value `2`, and "↓0" (off) → value `5`.

| Register | Semantic (from button labels) | Values written | Confidence |
|----------|-------------------------------|----------------|------------|
| 1000 | Drum motor — sub-role unknown (paired with 1002) | 2, 5 | Medium |
| 1001 | Gas / burner capacity (slider) | slider value | High |
| 1002 | Drum motor — sub-role unknown (paired with 1000) | 2, 5 | Medium |
| 1003 | Drum speed (slider) | slider value | High |
| 1004 | Destoner on/off | 2, 5 | Medium |
| 1005 | Loader on/off | 2, 5 | Medium |
| 1006 | Afterburner on/off | 2, 5 | Medium |
| 1007 | RESET Afterburner (write-once) | 2 | Low |
| 1008 | Charge — open/close (momentary in button: write 2, sleep 10s, write 5) | 2, 5 | Medium |
| 1009 | Discharge — open/close (momentary in button: write 2, sleep 10s, write 5) | 2, 5 | Medium |
| 1010 | Release on/off | 2, 5 | Medium |

**Register 1000/1002 pair:** Always written together in the same command:
- Drum on: `writeSingle([1,1000,2],[1,1002,2])`
- Drum off: `wcoil(1,2003,0); writeSingle([1,1000,5],[1,1002,5])`

They are always written to the same value simultaneously. This suggests they may control two separate parts of the drum motor circuit, or that the PLC requires both registers to agree for the state change to take effect. Exact sub-role requires machine validation.

#### Register 3904 — extra slider

| Register | Semantic | Slider factor | Confidence |
|----------|----------|---------------|------------|
| 3904 | Unknown (no button label) | 45 | Low |

No button action ever touches 3904. Only a slider. Given the high factor (45) and no offset, and placement far from the 1000-range, this may be a temperature setpoint or a cooling-related parameter. Requires machine validation.

#### Register 20 — PID SV setpoint

| Register | Semantic | Multiplier |
|----------|----------|------------|
| 20 | PID setpoint (SV) | ×1 |

Written by Artisan's external PID path when PID is active.

### PID tuning registers

| Register | Semantic | Confidence |
|----------|----------|------------|
| 100 | Kp | High |
| 150 | Ki | High |
| 200 | Kd | High |

Written by `setPID()` in the Artisan PID path.

---

### Coil writes (`wcoil`)

| Coil | Semantic (from button labels) | States written | Write pattern | Confidence |
|------|-------------------------------|----------------|---------------|------------|
| 2003 | Burner relay on/off | 0, 1 | Simple toggle | High |
| 2004 | RESET Burner — momentary trigger | 1 → sleep(2s) → 0 | Pulse, not sustained | High |
| 2005 | Cooler relay on/off | 0, 1 | Simple toggle | High |
| 2006 | Mixer relay on/off | 0, 1 | Simple toggle | High |
| 2009 | PID enable/disable | 0, 1 | PID_ON / PID_OFF action | High |

**Coil 2004 safety note:** This is a timed pulse — Artisan writes `1`, waits 2 seconds, then writes `0`. This is consistent with a reset or ignition trigger that physically needs to stay engaged for a moment. **Never hold coil 2004 at `1` indefinitely.**

**Drum off sequence:** The drum-off button does two things in sequence: `wcoil(1,2003,0)` (burner off) followed by `writeSingle([1,1000,5],[1,1002,5])` (drum motor off). This implies drum should not stop while burner is running — a safety ordering.

---

## Sliders — decoded

From `BSC_automatic.aset [Sliders]` section:

```
slidercommands = "writeSingle(1,1003,{})", "writeSingle(1,1001,{})", [empty], "writeSingle(1,3904,{})"
sliderfactors  = 2.57, 4, 1, 45
slideroffsets  = 100, 100, 0, 0
slidermin      = 0, 0, 0, 0
slidermax      = 100, 100, 100, 100
slidervisibilities = 1, 1, 0, 1
```

Artisan computes the written value as: `round(slider_position × factor + offset)`

| Slider | Register | Factor | Offset | Position 0 → written | Position 100 → written | Semantic |
|--------|----------|--------|--------|----------------------|------------------------|----------|
| 1 | 1003 | 2.57 | 100 | 100 | 357 | Drum speed |
| 2 | 1001 | 4 | 100 | 100 | 500 | Gas / burner capacity |
| 3 | — | — | — | (inactive, hidden) | — | — |
| 4 | 3904 | 45 | 0 | 0 | 4500 | Unknown |

**Slider units are unknown.** The factor/offset gives the PLC's raw register range, but whether units are RPM, % × 10, or machine-specific is unconfirmed without machine docs or live observation.

---

## Button commands — full decode (BSC_full_automatic)

Ordered as in `extraeventslabels`:

| # | Button label | Command | Register/coil | Values |
|---|-------------|---------|---------------|--------|
| 1 | ↑1 (Drum on?) | `writeSingle([1,1000,2],[1,1002,2])` | 1000, 1002 | 2, 2 |
| 2 | ↓0 (Drum off?) | `wcoil(1,2003,0); writeSingle([1,1000,5],[1,1002,5])` | coil 2003, reg 1000/1002 | 0; 5, 5 |
| 3 | (blank) | — | — | — |
| 4 | Afterburner ↑1 | `writeSingle(1,1006,2)` | 1006 | 2 |
| 5 | Afterburner ↓0 | `writeSingle(1,1006,5)` | 1006 | 5 |
| 6 | (blank) | — | — | — |
| 7 | Loader ↑1 | `writeSingle(1,1005,2)` | 1005 | 2 |
| 8 | Loader ↓0 | `writeSingle(1,1005,5)` | 1005 | 5 |
| 9 | (blank) | — | — | — |
| 10 | Charge ↑o | `writeSingle(1,1008,2)` | 1008 | 2 |
| 11 | Charge ↓c | `writeSingle(1,1008,5)` | 1008 | 5 |
| 12 | (blank) | — | — | — |
| 13 | RESET ↑ (Burner) | `wcoil(1,2004,1); sleep(2); wcoil(1,2004,0)` | coil 2004 | 1 → 0 |
| 14 | Cooler ↑1 | `wcoil(1,2005,1)` | coil 2005 | 1 |
| 15 | Cooler ↓0 | `wcoil(1,2005,0)` | coil 2005 | 0 |
| 16 | (blank) | — | — | — |
| 17 | Mixer ↑1 | `wcoil(1,2006,1)` | coil 2006 | 1 |
| 18 | Mixer ↓0 | `wcoil(1,2006,0)` | coil 2006 | 0 |
| 19 | (blank) | — | — | — |
| 20 | Discharge ↑o | `writeSingle(1,1009,2)` | 1009 | 2 |
| 21 | Discharge ↓c | `writeSingle(1,1009,5)` | 1009 | 5 |
| 22 | (blank) | — | — | — |
| 23 | Destoner ↑1 | `writeSingle(1,1004,2)` | 1004 | 2 |
| 24 | Destoner ↓0 | `writeSingle(1,1004,5)` | 1004 | 5 |
| 25 | (blank) | — | — | — |
| 26 | Release ↑o | `writeSingle(1,1010,2)` | 1010 | 2 |
| 27 | Release ↓c | `writeSingle(1,1010,5)` | 1010 | 5 |
| 28 | (blank) | — | — | — |
| 29 | RESET Afterburner | `writeSingle(1,1007,2)` | 1007 | 2 |

**Momentary buttons (from `buttonactionstrings`):**
- `writeSingle(1,1008,2); sleep(10); writeSingle(1,1008,5)` → Charge: open, hold 10s, close
- `writeSingle(1,1009,2); sleep(10); writeSingle(1,1009,5)` → Discharge: open, hold 10s, close

---

## Modbus RTU connection path (from `modbusport.py`)

### How RTU serial connect works

```
connect() [sync wrapper]
  → asyncio.run_coroutine_threadsafe(connect_async(), loop)
    → if not isConnected():
        reset commError = 0
        create AsyncModbusSerialClient(
          framer=FramerType.RTU,
          port=self.comport,
          baudrate=self.baudrate,
          bytesize=self.bytesize,
          parity=self.parity,
          stopbits=self.stopbits,
          retries=self.serial_readRetries,
          timeout=min(delay/2000, self.timeout)  ← capped at half sampling interval
        )
        await client.connect()
        updateActiveRegisters()        ← build register sequence cache
        clearReadingsCache()
        await asyncio.sleep(modbus_serial_connect_delay)  ← user-configurable connect delay
        sendmessage('Connected via MODBUS')
```

**Key facts:**
- Connection is lazy — `connect()` is called before first read/write if `_client is None`
- `_asyncLoopThread` is created on first `connect()` and holds the async event loop
- Timeout is `min(sampling_delay / 2000, 0.4)` — with default 1000ms delay → 0.4s
- Serial connect delay (`modbus_serial_connect_delay`) is applied only for RTU/ASCII, not TCP

### Error handling and reconnect strategy

Artisan uses a **lazy reconnect** model — not an active reconnect daemon:

```
On read/write error:
  commError += 1
  disconnectOnError() called
    → if disconnect_on_error AND (commError > acceptable_errors OR not isConnected()):
        disconnect()

On next sampling tick:
  readActiveRegisters()
    → if not isConnected(): connect() is called again

On successful read:
  clearCommError()
    → if commError > 0: adderror('Modbus Communication Resumed')
    → commError = 0
```

This means: after an error the connection is dropped, and the next sampling tick triggers an automatic reconnect. There is no independent reconnect thread.

### Polling model (optimizer)

```
comm.MODBUSread() [called each sampling tick]
  → modbusport.readActiveRegisters()
      → updateActiveRegisters()  ← groups active channels by (FC code, deviceId)
      → read_active_registers_async()
          → batch reads FC3/FC4 registers in sequence blocks
          → stores raw values in readingsCache
  → per-channel: read_registers(deviceId, register)
      → cache hit: return from readingsCache
      → cache miss: individual read
  → processChannelData(value, div, mode)
      → apply ÷10 or ÷100 divider
      → C/F unit conversion if needed
```

For Besca with `optimizer=true` and `fetch_max_blocks=false`:
- Registers 6 and 7 are both FC3/deviceId=1 → batched in a single read sequence
- Register cache populated once per tick, then both channels extract from it

---

## Confirmed minimum read/write set for diagnostics shell

### Read (all FC3, deviceId=1, ÷10 → °C)
```
register 6   → BT (bean temperature)
register 7   → ET (exhaust temperature)
register 10  → extra channel (display raw; validate semantic before labelling)
```

### Write (safe to test)
```
writeSingle(1, 1001, N)     → gas/burner capacity
writeSingle(1, 1003, N)     → drum speed
wcoil(1, 2009, 0/1)         → PID off/on
writeSingle(1, 20, N)       → SV setpoint (only when PID active)
wcoil(1, 2003, 0/1)         → burner off/on
wcoil(1, 2005, 0/1)         → cooler off/on
wcoil(1, 2006, 0/1)         → mixer off/on
```

### Write — hold for machine validation
```
wcoil(1, 2004, 1→0)         → RESET Burner pulse — unknown physical consequence
writeSingle(1, 1000/1002, 2/5)  → drum motor start/stop — always write as pair
writeSingle(1, 1008, 2/5)   → charge gate — hold or momentary? validate first
writeSingle(1, 1009, 2/5)   → discharge gate — same
registers 1004–1007, 1010   → secondary actuators — validate semantics first
register 3904                → unknown — validate before touching
```

---

## Safety notes

1. **Coil 2004** — Artisan always uses it as a timed pulse (write 1, wait 2s, write 0). Do not hold it at 1. Unknown physical consequence if sustained.
2. **Drum off sequence** — Artisan always turns burner off (`wcoil 2003 = 0`) before stopping drum motor (reg 1000/1002 = 5). Respect this ordering. Do not stop drum while burner is active.
3. **Charge/Discharge gates (1008/1009)** — Both have momentary button variants (write start value, wait 10s, write stop value). These may control physical gates/valves. Do not leave in open state unintentionally.
4. **Slider ranges** — reg 1001 slider can write values up to 500, reg 1003 up to 357. Units unconfirmed. Use conservative values during testing until range limits are machine-validated.

---

## Open questions

| # | Question | How to validate |
|---|----------|-----------------|
| Q1 | What is register 10? (user has it mapped; no label in any preset) | Read live, observe response |
| Q2 | What does the 1000/1002 register pair represent within drum motor control? | Capture read state before/after drum start/stop |
| Q3 | Is the value encoding (2=on, 5=off) universal across all 1000–1010 regs, or do some regs use different values? | Test each register individually |
| Q4 | What physical unit does register 3904 represent? What is its safe range? | Read live at different slider positions |
| Q5 | Are slider output ranges (up to 500 for reg 1001, up to 357 for reg 1003) actually safe to use across their full range? | Observe machine behaviour at high values |
| Q6 | Does register 7 in FC3 read ET or ambient temp? Artisan labels it ET but physical wiring may differ | Compare to known temperatures |
| Q7 | Does deviceId=2 (from BSC_manual_v1) still exist on current machines? | Scan deviceId=2 on the bus |
| Q8 | What does RESET Afterburner (writeSingle 1007 = 2) actually reset? | Need manual + machine observation |

---

## Firmware summary table

| Preset | Baudrate | BT register | ET register | FC | DeviceId | Has writes | Has PID |
|--------|----------|-------------|-------------|-----|----------|------------|---------|
| BSC_automatic | 115200 | 6 | 7 | 3 | 1 | Yes | Yes |
| BSC_full_automatic | 115200 | 6 | 7 | 3 | 1 | Yes (extended) | Yes |
| BSC_manual_v1 | 9600 | 0 | 0 | 4 | 1 / **2** | No | No |
| BSC_manual_v2 | 9600 | 45 | 46 | 3 | 1 | No | No |
| Bee | 9600 | 0 | 10 | 4 | 1 | No | No |
| Bee_v2 | 9600 | 45 | 46 | 3 | 1 | No | No |

The user's machine runs the **BSC_automatic / BSC_full_automatic** firmware (115200 baud, registers 6/7, FC3, full write support).
