# Trobrat Bernin in RoastArtisan

The machine preset **Config → Machine → Trobrat → Bernin-Control** enables the
roaster-specific gateway inside RoastArtisan. The separate `Start-Control`
window is not needed with this preset. The gateway connects to the Siemens PLC
at `192.168.0.1:102` and exposes the validated telemetry and command map only
on `127.0.0.1:15020` for RoastArtisan's existing Modbus inputs and actions.
The Weintek panel remains connected as before. Other machine presets do not
start the gateway.

This mapping comes from the owner's Weintek project and captured traffic for
**this specific Bernin/Trobrat controller program**. It is not a preset for
other Trobrat machines or PLC projects. Save the current settings before
selecting the machine preset. If a standalone BerninControl window is already
using port 15020, close it and reload the preset.

## What the preset provides

- BT/ET through the existing S7 temperature channels, plus the burner's output
  percentage on S7 channel 3.
- Gas pressure, air pressure, active drum setpoint and air PID output as four
  local Modbus readings.
- Manual controls for drum setpoint (0–65 rpm), air pressure setpoint (0–300 Pa)
  and gas pressure setpoint (0–20 mbar). Additional buttons control mixer M3,
  cooler fan M4 and destoner M6.
- The gateway reads the current PLC context before each command, checks the
  configured operating mode and limits, sends at most one write and verifies
  the stored command. No PLC write occurs on startup or during ordinary polling.

The software checks do not replace the PLC's physical interlocks. Positive gas
pressure can start heating in a panel-enabled mode. The `Gas 0` button uses
the same communication path and is not an emergency stop. A communication
failure may leave the last PLC setpoint in force; use the roaster's panel and
hardware controls for shutdown.

The gateway intentionally does not change PID preheat modes, BT/ET selection,
the PLC program or Weintek project. Those controls remain on the panel until
their commands and mode transitions have been validated separately.

The owner-tested standalone gateway and its captured-protocol tests are
preserved under `src/artisanlib/trobrat/`. Protocol fixtures contain only the
selected read and write frames needed to check the implementation.
