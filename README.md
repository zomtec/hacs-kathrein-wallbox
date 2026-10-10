# Kathrein Wallbox

Integrate a Kathrein Wallbox with Home Assistant over local Modbus TCP. Monitor charging and meter data, inspect EVSE diagnostics, and set supported EMS charging values.

## Disclaimer

This is an independent community project and is not affiliated with, endorsed by, or sponsored by KATHREIN Digital Systems GmbH, the manufacturer of the Wallbox. Kathrein and related product names are trademarks of their respective owners.

[![HACS custom repository](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://www.hacs.xyz/docs/faq/custom_repositories/)
[![Latest release](https://img.shields.io/github/v/release/zomtec/hacs-kathrein-wallbox?style=flat-square)](https://github.com/zomtec/hacs-kathrein-wallbox/releases/latest)
[![License](https://img.shields.io/github/license/zomtec/hacs-kathrein-wallbox?style=flat-square)](LICENSE)
[![Commit activity](https://img.shields.io/github/commit-activity/y/zomtec/hacs-kathrein-wallbox?style=flat-square)](https://github.com/zomtec/hacs-kathrein-wallbox/commits)

> [!IMPORTANT]
> This integration communicates with the Wallbox locally over Modbus TCP. Enable the Modbus server in the Wallbox **easyOperate** configuration before adding the integration.

## Installation

### HACS

This repository is installed in HACS as a **custom repository**; it is not necessarily part of HACS's default catalog.

[![Add this repository to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=zomtec&repository=hacs-kathrein-wallbox&category=integration)

1. Open HACS and choose **Integrations**.
2. Open the menu (⋮), select **Custom repositories**, and add `zomtec/hacs-kathrein-wallbox` with category **Integration**. Or use the HACS button above.
3. Install **Kathrein Wallbox** and restart Home Assistant.

### Manual installation

Copy `custom_components/kathrein_wallbox` into the `custom_components` directory of your Home Assistant configuration, restart Home Assistant, then add the integration as described below.

## Set up the integration

[![Add Kathrein Wallbox to Home Assistant](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=kathrein_wallbox)

1. In Home Assistant, open **Settings > Devices & services > Add integration** and search for **Kathrein Wallbox**, or use the setup button above after installation.
2. Enter the Wallbox host or IP address. The default Modbus TCP port is `502`; the default unit ID is `0` (recommended by the register manual).
3. Choose a polling interval. It defaults to `15` seconds and can be set from `5` to `300` seconds. These connection settings can be changed later in the integration options.

The Wallbox must report mapping version `0x0002` and a readable serial number during setup. The integration uses the serial number to identify the device and prevent duplicate entries.

## What it provides

| Group | Entities |
| --- | --- |
| Meter | Per-phase voltage, current, and active power; total active power and energy; line frequency. |
| Charging | Charging state, session duration and energy, granted current and power. |
| EVSE diagnostics | Proximity pilot (PP) and control pilot (CP) states; relay states; EVSE fault flags. |
| EMS | EMS enabled state and readbacks for relay matrix, current, timeout, and timeout fallback values. |
| Meter diagnostics | A binary sensor indicating whether a usable meter is detected. |

Meter readings are optional and do not prevent EVSE and charging data from updating. Meter availability is checked against plausible mains references (voltage `80`-`300 V`, frequency `45`-`65 Hz`); rejected or implausible readings make meter entities unavailable. Meter entities are disabled by default if no meter is detected during setup. If the Wallbox has a meter, you can enable those entities from the entity registry and check the readings against the device.

## EMS control services

These Home Assistant services write EMS setpoints to Modbus holding registers. Every service requires `entry_id`, which selects the Wallbox configuration entry.

| Service | Register | Additional field and allowed values |
| --- | --- | --- |
| `set_ems_control_enabled` | `0x00A0` | `enabled`: `true` or `false` |
| `set_relay_matrix` | `0x00A1` | `value`: `line_1`, `line_2`, `line_3`, or `three_lines` |
| `set_charging_current` | `0x00A2` | `value`: `6`, `8`, `10`, `12`, `16`, `20`, `24`, or `32` A |
| `set_timeout_period` | `0x00A3` | `value`: `0` (off), `30`, `60`, `120`, `180`, `300`, or `600` seconds |
| `set_timeout_fallback_relay_matrix` | `0x00A4` | `value`: `line_1`, `line_2`, `line_3`, or `three_lines` |
| `set_timeout_fallback_current` | `0x00A5` | `value`: `0`, `6`, `8`, `10`, `12`, `16`, `20`, `24`, or `32` A |

For an 11 kW Wallbox, requests above `16 A` are rejected for both the charging-current setpoint and timeout fallback. A `0 A` value is available only for the timeout fallback; it pauses charging and grants no charging current.

Example service call to request `16 A` (replace the placeholder with the Wallbox's config entry ID):

```yaml
service: kathrein_wallbox.set_charging_current
data:
	entry_id: "<config-entry-id>"
	value: "16"
```

These services write directly to the Wallbox. Check the phase selection, current, timeout, fallback behavior, and Wallbox rating before using them in automations. The integration does not write authentication tags or tariff registers.

## Troubleshooting

| Symptom | Checks |
| --- | --- |
| Cannot connect during setup | Confirm the host, port, and unit ID; make sure the Modbus server is enabled in easyOperate and the Home Assistant host can reach the Wallbox on the network. |
| Device is not supported | Confirm the device reports mapping version `0x0002` and a readable serial number. |
| Meter entities are unavailable | Meter data is optional. Check the meter readings and reference ranges above. If the Wallbox has a meter that was not detected during setup, enable its entities from the entity registry. |
| Need more information for a report | Download diagnostics from the Kathrein Wallbox config entry under **Settings > Devices & services** and attach them to an issue, after reviewing the data. |

## Compatibility and register notes

The integration uses local Modbus TCP and was developed against Register Mapping V1.5. The setup flow checks mapping version `0x0002`; this does not establish compatibility with every Wallbox model or firmware. Verify readings and write behavior on your specific device before relying on automated control.

The register manual describes FLOAT32 values as IEEE 754 but does not specify word order. The integration currently decodes them using big-endian word order; compare measurements with the Wallbox before relying on them. The manual describes register `0x005C` as energy in Wh. Session energy uses the UINT32 counter at `0x0069` and is also exposed in Wh.

## Diagnostics and privacy

Downloaded config-entry diagnostics include model and mapping information, meter availability, and register snapshots from the identity, EVSE, meter, and session-energy blocks. Serial-number registers `0x0011`-`0x0018` are removed. EMS control registers are not included. Review diagnostics before sharing them publicly.

## Support

Please [open an issue](https://github.com/zomtec/hacs-kathrein-wallbox/issues) for bug reports or feature requests. Include your Home Assistant version, Wallbox model and firmware if known, and relevant diagnostics with personal or network details reviewed.

## Acknowledgments

This integration was created with substantial assistance from GitHub Copilot.

## License

Original project materials are licensed under the MIT License. The Kathrein brand graphics and the Modbus register manual (including its extracted text) are excluded and remain subject to their respective rights holders' terms. See [LICENSE](LICENSE) and [LICENSE-SCOPE.md](LICENSE-SCOPE.md) for the license and exclusions.

## Brand assets

The Home Assistant brand images are sourced from the official Kathrein website:

- Icon: [Kathrein eMobility](https://www.kathrein-ds.com/wp-content/uploads/2026/05/kathrein_icon_emobility.webp)
- Logo: [Kathrein Digital Systems](https://www.kathrein-ds.com/wp-content/uploads/2026/04/kathrein_logo_600px.webp)
