# Kathrein Wallbox for Home Assistant

Home Assistant integration for Kathrein Wallboxes using local Modbus TCP and Register Mapping V1.5. It provides telemetry and EMS control services that write supported setpoints to the Wallbox.

## Installation

### HACS custom repository

After this project is imported to a public GitHub repository, add its repository URL in HACS under **Integrations > ⋮ > Custom repositories**. Select **Integration** as the category, add the integration through HACS, and restart Home Assistant. Then add **Kathrein Wallbox** from **Settings > Devices & services**.

### Manual installation

Copy `custom_components/kathrein_wallbox` into the `custom_components` directory in your Home Assistant configuration, restart Home Assistant, then add **Kathrein Wallbox** from **Settings > Devices & services**.

Before setup, enable the Modbus server in the Wallbox easyOperate configuration panel. Enter the Wallbox IPv4 address. The default port is `502`; the default unit ID is `0` as recommended by the register manual. Both can be changed in the setup form.

## Entities

The integration exposes per-phase voltage, current and active power; total active power, energy since production and line frequency; charging and pilot states; granted current and power; session duration and energy; relay states; and the documented EVSE fault bits. Meter measurements are optional: they become unavailable if their register block is rejected or if voltage/frequency values do not contain a plausible mains reference. The detection accepts 80-300 V and 45-65 Hz; out-of-range voltage/frequency readings are unavailable. Meter entities are disabled by default when no meter is detected during setup; enable them manually from the entity registry if the model has a meter but its readings do not meet those reference ranges. EVSE and charging entities continue to update independently. A diagnostic binary sensor reports whether a meter is detected.

Downloaded diagnostics include the registers used by the integration, with the serial-number register range redacted. Authentication tags and session GUIDs are not exposed.

## EMS control services

The integration writes EMS control values to Modbus holding registers `0x00A0`-`0x00A5`. The six services are available in Home Assistant automations and Developer Tools:

| Service | Register | Purpose |
| --- | --- | --- |
| `set_ems_control_enabled` | `0x00A0` | Enable or disable EMS control. |
| `set_relay_matrix` | `0x00A1` | Select the relay/phase configuration. |
| `set_charging_current` | `0x00A2` | Set the EMS charging-current request. |
| `set_timeout_period` | `0x00A3` | Set how long the EMS override remains active. |
| `set_timeout_fallback_relay_matrix` | `0x00A4` | Select the relay configuration used after timeout. |
| `set_timeout_fallback_current` | `0x00A5` | Set the fallback charging current used after timeout. |

Charging-current values are selected from the supported discrete values from `6 A` through `32 A`. For an 11 kW Wallbox, the integration rejects requests above `16 A`. The fallback current also supports `0 A`. A `0 A` setpoint pauses charging: it grants no charging current; it is not a request for zero-power charging while keeping current available.

These services write directly to the Wallbox. Check the selected phases, current, timeout, and fallback values before using them in automations. The integration does not expose authentication-tag writes or tariff registers.

## Compatibility and register notes

The config flow requires mapping version `0x0002` and a readable serial number. Floating-point registers currently use the Modbus-standard big-endian word order. The register document identifies the FLOAT32 encoding as IEEE 754 but does not state word order explicitly; compare the displayed measurements with the Wallbox before relying on them.

The device manual describes register `0x005C` as energy in Wh. The session counter uses UINT32 at `0x0069` and is also exposed in Wh. The integration has been developed against Register Mapping V1.5; verify the readings and write behavior for the specific Wallbox model and firmware before relying on automated control.

## License

Original project materials are licensed under the MIT License. The Kathrein brand graphics and the Modbus register manual (including its extracted text) are excluded and remain subject to their respective rights holders' terms. See [LICENSE](LICENSE) and [LICENSE-SCOPE.md](LICENSE-SCOPE.md) for the license and exclusions.

## Brand assets

The Home Assistant brand images are sourced from the official Kathrein website:

- Icon: [Kathrein eMobility](https://www.kathrein-ds.com/wp-content/uploads/2026/05/kathrein_icon_emobility.webp)
- Logo: [Kathrein Digital Systems](https://www.kathrein-ds.com/wp-content/uploads/2026/04/kathrein_logo_600px.webp)
