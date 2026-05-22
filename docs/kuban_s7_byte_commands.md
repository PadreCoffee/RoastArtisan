# Kuban S7 Byte Commands

This local Artisan patch adds `setDBbyte(dbnumber,start,value)` to S7 Command actions.

Use it for Kuban start/stop buttons because the panel capture showed that the roaster expects full control bytes, not only individual `Run` bit writes.

## Artisan Button Mapping

Set each button action to `S7 Command`.

| Button | Command |
| --- | --- |
| Drum ON | `setDBbyte(41,0,11)` |
| Drum OFF | `setDBbyte(41,0,9)` |
| Air ON | `setDBbyte(41,34,3)` |
| Air OFF | `setDBbyte(41,34,1)` |
| Agitator ON | `setDBbyte(41,68,11)` |
| Agitator OFF | `setDBbyte(41,68,9)` |
| Cooler ON | `setDBbyte(41,102,3)` |
| Cooler OFF | `setDBbyte(41,102,1)` |
| Burner ON | `setDBbyte(43,0,1)` |
| Burner OFF | `setDBbyte(43,0,0)` |
| Burner RESET | `setDBbyte(43,0,2);sleep(0.2);setDBbyte(43,0,0)` |

Pressure can stay on the existing working path:

```text
setDBfloat(57,2,{})
```

## Why Byte Writes

Panel capture showed these values:

| Signal | DB byte | ON | OFF |
| --- | ---: | ---: | ---: |
| Drum | `DB41.DBB0` | `0x0B` | `0x09` |
| Air | `DB41.DBB34` | `0x03` | `0x01` |
| Agitator | `DB41.DBB68` | `0x0B` | `0x09` |
| Cooler | `DB41.DBB102` | `0x03` | `0x01` |
| Burner | `DB43.DBB0` | `0x01` | `0x00` |

The previous `setDBbool(...)` commands only changed one bit and did not reproduce the full panel command byte.
