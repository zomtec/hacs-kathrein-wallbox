# KATHREIN-Wallbox – ModBus-Server – Register-Mapping

Text extracted from the PDF. Layout and spacing are preserved in text blocks.

## PDF page 1

```text
KATHREIN-Wallbox – ModBus-Server – Register-Mapping
Release Version    1.5
Release Date       20.10.2025



Change History
 Release Version   Release Date   Comment
       1.0          20.08.2024    1st Release
       1.1          09.09.2024    Layout improved and comments added
                                   UTC to Local Date and Time
       1.2          24.10.2024
                                   Meter-Frequency added
       1.3          04.11.2024    Comments added
                                   Unit changed from kWh to Wh at Register 0x005C (Total Energy since production)
                                    Value was correct in Wh, but unit was wrong at kWh
       1.4          11.06.2025
                                   Tag-Info added at Register 0x0070
                                    These registers represents the tag, that authorized the current charging-session
                                   Mapping-Version increased from 0x0001 to 0x0002
       1.5          20.10.2025     Register for authentication via ModBus added
                                   Register for charging-actions (Start / Stop) added




KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```
## PDF page 2

```text
Communication Interface
The KATHREIN-ModBus-Server can be accessed via standard ModBus-TCP protocol according to IEC 61158 and IEC 61784-2 (CPF 15/1).
Hereby the associated IPv4-address of the Wallbox and the port 502 are required.
At the moment, the Unit-ID is ignored, but 0x00 (Broadcast) is recommended for future compatibility.
The ModBus-Server functionality has to be generally enabled or disabled in the easyOperate configuration panel.
By factory-default, ModBus-Server is disabled.


ModBus-TCP Protocol Frame
 Section                                      Byte Count     Description
                                                   2         Transaction-ID
 MBAP-Header                                       2         Protocol-ID (0x0000 for ModBus-TCP)
 (ModBus Application Protocol Header)              2         Count of PDU Data + 2 (inclusive Unit-ID and Function-Code)
                                                   1         Unit-ID (0x00)
 PDU                                               1         Function-Code
 (Protocol Data Unit)                              N         Data


Data Types
     Data Type          Register     Byte    Description
                         Count      Count
 SINT16 / UINT16           1          2      Integer data types (SINTxy / UINTxy) are stored as big-endian (most significant register / byte first)
 SINT32 / UINT32           2          4                                   “                                 “
 SINT64 / UINT64           4          8                                   “                                 “
    FLOAT32                2          4      32-bit Float (Single) according to IEEE 754
     STRING                N       0…Nx2     0-terminated String; String ends either by character 0x00 or by the count of associated registers
     BINARY                N        Nx2      Byte-aligned data-sequence without dedicated data type (little-endian – LSB first)


Registers Access and Function Codes
The KATHREIN-ModBus-Server just responds on Holding-Registers:
Read multiple registers    0x03
Write multiple registers   0x10
Write single register      0x06


KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```
## PDF page 3

```text
Register Table (Holding-Registers)
 Register   Register    Byte   Data Type   R/W Register                      Register                                              Unit
 Address     Count     Count                   Name                          Description
                                                                             The decimal-version of this register-mapping
  0x0000        1        2      UINT16      R    Header: Mapping-Version
                                                                             Current Version = 0x0002
  0x0001        8        16     STRING      R    Device: Number              Format          : "620xxxxx(-yyyy)"
  0x0009        8        16     STRING      R    Device: Type                Format          : "ACxx(E)"
  0x0011        8        16     STRING      R    Device: Serial              Format          : "G0Rxxxxxxx"
                                                                             Bits 0-1        : Power-Class
                                                                             0x0001          : 11kW (3 x 16A)
                                                                             0x0002          : 22kW (3 x 32A)

                                                                             Bit 4           : Cable / Plug
                                                                             0x0010          : "0" = Cable, "1" = Plug

                                                                             Bit 7           : Eichrecht
                                                                             0x0080          : "0" = Standard, "1" = Eichrecht
  0x0019        1        2      UINT16      R    Device: Info
                                                                             Bits 8-15       : Relais-Capability
                                                                             0x0100          : L1 only (1 Line)
                                                                             0x0200          : L2 only (1 Line)
                                                                             0x0400          : L3 only (1 Line)
                                                                             0x1000          : L1 and L2 (2 Lines)
                                                                             0x2000          : L1 and L3 (2 Lines)
                                                                             0x4000          : L2 and L3 (2 Lines)
                                                                             0x8000          : L1 and L2 and L3 (3 Lines)
                                                                             0               : L1-L2-L3 (default)
                                                                             1               : L1-L3-L2 (invalid phase rotation)
                                                                             2               : L2-L3-L1
  0x001A        1        2      UINT16      R    Device: Line-Mapping
                                                                             3               : L2-L1-L3 (invalid phase rotation)
                                                                             4               : L3-L1-L2
                                                                             5               : L3-L2-L1 (invalid phase rotation)
                                                                             Local Date & Time according to "UNIX-Format"
  0x001B        4        8      UINT64      R    Device: Timestamp (local)                                                         sec
                                                                             Seconds since 01.01.1970 00:00:00
  0x001F       17        34     BINARY      R    Reserved 1 3)               Reserved (all byte = 0x00)

KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```

## PDF page 4

```text
  0x0030        2        4      FLOAT32     R    Meter: U1                          Line 1           : Line to Neutral Volts             V
  0x0032        2        4      FLOAT32     R    Meter: U2                          Line 2           : Line to Neutral Volts             V
  0x0034        2        4      FLOAT32     R    Meter: U3                          Line 3           : Line to Neutral Volts             V
  0x0036        2        4      FLOAT32     R    Meter: I1                          Line 1           : Current                           A
  0x0038        2        4      FLOAT32     R    Meter: I2                          Line 2           : Current                           A
  0x003A        2        4      FLOAT32     R    Meter: I3                          Line 3           : Current                           A
 0x003C         2        4      FLOAT32     R    Meter: P1 (active)                 Line 1           : active Power                      W
  0x003E        2        4      FLOAT32     R    Meter: P2 (active)                 Line 2           : active Power                      W
  0x0040        2        4      FLOAT32     R    Meter: P3 (active)                 Line 3           : active Power                      W
  0x0042        2        4      FLOAT32     R    Meter: S1 (apparent) 3)            Line 1           : apparent Power                    VA
  0x0044        2        4      FLOAT32     R    Meter: S2 (apparent)     3)
                                                                                    Line 2           : apparent Power                    VA
  0x0046        2        4      FLOAT32     R    Meter: S3 (apparent) 3)            Line 3           : apparent Power                    VA
  0x0048        2        4      FLOAT32     R    Meter: Q1 (reactive)    3)
                                                                                    Line 1           : reactive Power                    VAr
  0x004A        2        4      FLOAT32     R    Meter: Q2 (reactive)    3)
                                                                                    Line 2           : reactive Power                    VAr
 0x004C         2        4      FLOAT32     R    Meter: Q3 (reactive) 3)            Line 3           : reactive Power                    VAr
  0x004E        2        4      FLOAT32     R    Meter: PF1   3)
                                                                                    Line 1           : Power Factor (cos φ, 0.0 … 1.0)
  0x0050        2        4      FLOAT32     R    Meter: PF2 3)                      Line 2           : Power Factor (cos φ, 0.0 … 1.0)
  0x0052        2        4      FLOAT32     R    Meter: PF3   3)
                                                                                    Line 3           : Power Factor (cos φ, 0.0 … 1.0)
  0x0054        2        4      FLOAT32     R    Meter: P tot (active)              Total active Power                                   W
  0x0056        2        4      FLOAT32     R    Meter: S tot (apparent)       3)
                                                                                    Total apparent Power                                 VA
  0x0058        2        4      FLOAT32     R    Meter: Q tot (reactive) 3)         Total reactive Power                                 VAr
  0x005A        2        4      FLOAT32     R    Meter: PF tot     3)
                                                                                    Total Power Factor (cos φ, 0.0 … 1.0)
 0x005C         2        4      FLOAT32     R    Meter: W tot                       Total Energy (since production)                      Wh
  0x005E        2        4      FLOAT32     R    Meter: Frequency                   Line Frequency                                       Hz




KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```

## PDF page 5

```text
                                                                        0                : Idle
                                                                        1                : EV Connected
                                                                        2                : Authentication Waiting
                                                                        3                : Authentication Confirmed
  0x0060        1        2      UINT16      R    EVSE: Charging-State   4                : Charging Active
                                                                        5                : Charging Paused
                                                                        6                : Charging Completed
                                                                        7                : RFID-Pairing
                                                                        0xFFFF           : Error

                                                                        0x0000           : No Error
                                                                        0x0001           : Relais welded
                                                                        0x0002           : Residual DC-Current detected (RCD)
                                                                        0x0004           : Socket Lock-Detection Error
                                                                        0x0008           : Charging Overcurrent
  0x0061        1        2      UINT16      R    EVSE: Error-States
                                                                        0x0010           : CP-D: Ventilation not available
                                                                        0x0020           : CP-E: Short-Circuit (CP-PE)
                                                                        0x0040           : CP-F: Loop broken (CP-PE)
                                                                        0x0080           : PP-Error (Short-Circuit)
                                                                        0x8000           : Internal Error

                                                                        Plug-Variant:
                                                                        0                : Cable not connected
                                                                        13               : 13 A (1500 Ω)
                                                                        20               : 20 A (680 Ω)
                                                                        32               : 32 A (220 Ω)
  0x0062        1        2      UINT16      R    EVSE: PP-State
                                                                        63               : 63 A (100 Ω)
                                                                        0xFFFF           : Error (invalid PP-Resistor)

                                                                        Cable-Variant:
                                                                        0                : fix Cable mounted




KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```

## PDF page 6

```text
                                                                                 0                : A (EV not detected, standby)
                                                                                 1                : B (EV detected, ready to charge)
                                                                                 2                : C (EV charging)
  0x0063        1        2      UINT16      R    EVSE: CP-State                  3                : D (EV charging with fan)
                                                                                 4                : E (CP Short-Circuit)
                                                                                 5                : F (EVSE not available, CP = -12VDC)
                                                                                 all other values : Undefined / Error

                                                                                 0x0000           : Relais OFF
                                                                                 0x0001           : Relais L1 activated
  0x0064        1        2      UINT16      R    EVSE: Relais-State
                                                                                 0x0002           : Relais L2 activated
                                                                                 0x0004           : Relais L3 activated
                                                                                 Granted charging current per Line
  0x0065        1        2      UINT16      R    EVSE: Granted Current           (related to CP-Signal)                                     mA
                                                                                 0, 6000 … 32000
                                                                                 Granted charging power
                                                                                 (power-sum of all active lines, related to CP-Signal)
  0x0066        1        2      UINT16      R    EVSE: Granted Power                                                                         W
                                                                                 1380 … 22080 @230VAC
                                                                                 (depending on Power-Class and active Relais)
  0x0067        2        4      UINT32      R    Charging: Duration              Charging Duration                                          sec
  0x0069        2        4      UINT32      R    Charging: Energy                Charging Energy (per charging session)                     Wh
  0x006B        1        2      UINT16      R    Charging: Tariff Info 3)        Charging Tariff Info & Currency (TBD)
 0x006C         1        2      UINT16      R    Charging: Current Tariff   3)
                                                                                 Charging Tariff for active charging session               0,001€
 0x006D         1        2      UINT16     R/W Charging: Next Tariff 3)          Charging Tariff for next charging session                 0,001€
  0x006E        2        4      BINARY      R    Reserved 2   3)
                                                                                 Reserved (all byte = 0x00)
                                                                                 Hex-coded Tag-Info (e.g. “RFID:A07E3F27FFE0” + 0x00)
  0x0070       24        48     STRING      R    Charging: Current Tag-Info      Valid for current / last charging session
                                                                                 In case of free charging without authentication: ”VOID”
                                                                                 Unique (global) individual ID for each charging session
                                                                                 Valid for current / last charging session
  0x0088       18        36     STRING      R    Charging: Current GUID          String has no terminating 0x00 and ends after 36
                                                                                 characters
                                                                                 Example: ”36598160-9E55-4B09-1702-7ED324945443”
  0x009A        6        12     BINARY      R    Reserved 3 3)                   Reserved (all byte = 0x00)


KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```

## PDF page 7

```text
                                                 EMS-Control:                 0x8000         : Enable EMS-Control
  0x00A0        1        2      UINT16     R/W
                                                 Control-Register             Default = 0x0000 (EMS-Control disabled)
                                                                              according to Relais-Capability
                                                                              0x0001          : Line 1
                                                 EMS-Control:
  0x00A1        1        2      UINT16     R/W                                0x0002          : Line 2 (reserved for future)
                                                 Setpoint Relais-Matrix 1)
                                                                              0x0004          : Line 3 (reserved for future)
                                                                              Default = 0x0007 (3 Lines)
                                                                              0              : Charging Paused
                                               EMS-Control:                   6000 … 32000 : Charging
  0x00A2        1        2      UINT16     R/W                                                                                         mA
                                               Setpoint Charging Current      0xFFFF         : Charging Cancel
                                                                              Default = max. Current according to Power-Class
                                                                              0               : Timeout deactivated
                                               EMS-Control:                   >0              : Timeout activated
  0x00A3        1        2      UINT16     R/W                                                                                         sec
                                               Timeout Period                 (each Setpoint-Write-Cycle resets the Timer)
                                                                              Default = 0 (Timeout deactivated)
                                                                              0x0001         : Line 1
                                               EMS-Control:                   0x0002         : Line 2
  0x00A4        1        2      UINT16     R/W
                                               Timeout Fallback Pattern 2)    0x0004         : Line 3
                                                                              Default = 0x0007 (3 Lines)
                                                                              Timeout fallback charging current
                                                 EMS-Control:
  0x00A5        1        2      UINT16     R/W                                0, 6000 … 32000                                          mA
                                                 Timeout Fallback Current
                                                                              Default = 6000
  0x00A6       10        20     BINARY     R/W Reserved 4 3)                  Reserved (all byte = 0x00)
                                                                              Tag-ID for authentication via register ”Tag-Action”
  0x00B0       16        32     STRING     R/W Authentication: Tag-ID 4)
                                                                              terminated by 0x00 or maximum length
                                                                              0x0000            : RFID
 0x00C0         1        2      UINT16     R/W Authentication: Tag-Type 4)    0x0001            : MAC (EV-MAC via ISO 15118)
                                                                              ...               :...
                                                                              Action is active for 60 seconds until EV is connected.
                                                                              If EV is connected after a timeout of 60 seconds, this
                                                 Authentication: Tag-Action
 0x00C1         1        2      UINT16     R/W   4)                           action will be discarded.
                                                                              0x0001            : Start charging
                                                                              0x0002            : Stop charging




KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```

## PDF page 8

```text
1) "Setpoint Relais-Matrix" will be used in interaction with “Setpoint Charging Current" command.
2) A combination of the 3 Lines is possible, according to the Relais-Capability. Unsupported Lines are ignored.
3) Reserved for future use.
4) Functionality has to be enabled / configured in easyOperate




KATHREIN-Wallbox – ModBus-Server – Register-Mapping V1.5
```
