# Kathrein Wallbox

Integrate a Kathrein Wallbox with Home Assistant over local Modbus TCP. Monitor charging and meter data, inspect EVSE diagnostics, and set supported EMS charging values.

## Disclaimer

This is an independent community project and is not affiliated with, endorsed by, or sponsored by KATHREIN Digital Systems GmbH, the manufacturer of the Wallbox. Kathrein and related product names are trademarks of their respective owners.

[![License](https://img.shields.io/github/license/zomtec/hacs-kathrein-wallbox?style=flat-square)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/zomtec/hacs-kathrein-wallbox?style=flat-square)](https://github.com/zomtec/hacs-kathrein-wallbox/releases/latest)
[![Commit activity](https://img.shields.io/github/commit-activity/y/zomtec/hacs-kathrein-wallbox?style=flat-square)](https://github.com/zomtec/hacs-kathrein-wallbox/commits)
[![HACS custom repository](https://img.shields.io/badge/HACS-Custom-41BDF5?style=flat-square)](https://www.hacs.xyz/docs/faq/custom_repositories/)

> [!IMPORTANT]
> This integration communicates with the Wallbox locally over Modbus TCP. Enable the Modbus server in the Wallbox web interface under **Settings > Modbus TCP control** before adding the integration.

## Supported devices

The integration targets the KATHREIN KWB-AC series:

| Model | Status |
| --- | --- |
| KWB-AC20 | Should work if the Wallbox reports mapping version `0x0002`. |
| KWB-AC35 | Tested. |
| KWB-AC40 | Should work if the Wallbox reports mapping version `0x0002`. |
| KWB-AC40 E | Should work if the Wallbox reports mapping version `0x0002`. |
| KWB-AC60 | Should work if the Wallbox reports mapping version `0x0002`. |
| KWB-AC60 E | Should work if the Wallbox reports mapping version `0x0002`. |

The setup flow rejects Wallboxes that do not report mapping version `0x0002`. If you use a model other than the KWB-AC35, please report whether it works by [opening an issue](https://github.com/zomtec/hacs-kathrein-wallbox/issues).

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
3. Choose a polling interval. It defaults to `15` seconds and can be set from `5` to `300` seconds.
4. Decide whether to turn on **Allow control by Home Assistant**. It is off by default, see [Control by Home Assistant](#control-by-home-assistant).

To change the host, port, or unit ID later, use **Reconfigure**; it refuses a device with a different serial number. The polling interval and **Allow control by Home Assistant** are changed in the integration options (**Configure**).

The Wallbox must report mapping version `0x0002` and a readable serial number during setup. The integration uses the serial number to identify the device and prevent duplicate entries. The device page shows the device number as model ID and links to the Wallbox web interface at `http://<host>`.

### Discovery

Home Assistant discovers a Wallbox on the local network through DHCP, by its hostname `KWB<serial number>` and the Kathrein MAC address prefix `00:D0:55`. A discovered Wallbox shows up under **Settings > Devices & services** as **Discovered**. Confirm it, check the port and unit ID, and choose the polling interval and **Allow control by Home Assistant** as in a manual setup; the integration reads the Wallbox before adding it. Discovery relies on the Home Assistant DHCP integration, which is part of the default configuration. If the Wallbox is not discovered, add it manually as described above.

When a configured Wallbox gets a new IP address, discovery stores the new address in its entry and reloads the integration, but only if the Wallbox no longer answers at the configured host and does answer at the new IP address with the configured port and unit ID. A working host, such as a Modbus proxy, is never replaced.

## What it provides

| Group | Entities |
| --- | --- |
| Meter | Per-phase voltage, current, and active power; total active power and energy; grid frequency. |
| Charging | Charging state, session duration and energy, granted charging current and power; authorization tag and session ID of the current or last charging session. |
| EVSE diagnostics | Proximity pilot (PP) and control pilot (CP) states; relay states; EVSE fault flags. |
| EMS | Readbacks for the timeout period and the timeout fallback relay matrix and current. |
| EMS controls | `Charging current` number input box (0 A to pause, or 6 to 32 A in 1 A steps) and `Phases` select (`Phase 1` or `3 Phases`). |
| EMS diagnostics | `EMS control` binary sensor showing whether EMS control is active, whether turned on by Home Assistant or by another energy manager. |
| Meter diagnostics | A binary sensor indicating whether a meter was detected. Once detected, it stays on. |

Detail entities are disabled by default and can be enabled from the entity registry: per-phase voltage, current and active power, grid frequency, PP and CP states, relay states, EMS readbacks, EVSE fault flags, authorization tag and charging session ID. Enable the fault flags if you want automations for them. Disabling an EMS readback does not affect the [EMS keep-alive](#ems-keep-alive).

The authorization tag sensor shows the tag that authorized the current or last charging session as reported by the Wallbox, for example `RFID:A07E3F27FFE0`, or `VOID` when the Wallbox is set to charge without authentication. The tag is personal data: Home Assistant records its history once you enable it. The charging session ID is the GUID the Wallbox assigns to each charging session. If the Wallbox does not answer for these registers (`0x0070`-`0x0099`), both sensors become unavailable without affecting the other entities.

Meter readings are optional and do not prevent EVSE and charging data from updating. The meter is checked on the first successful read of its registers after setup against plausible mains references (voltage `80`-`300 V`, frequency `45`-`65 Hz`), and the result is stored. A detected meter stays detected; later failed reads only make meter entities unavailable until the meter answers again, and implausible single values are shown as unknown. Without a detected meter, its registers are not read again until the integration is reloaded; each reload or Home Assistant restart repeats the check once. Meter entities are disabled by default while no meter is detected.

## Control by Home Assistant

Home Assistant only reads the Wallbox until you turn on **Allow control by Home Assistant** during setup or later in the integration options (**Configure**). Control has to be allowed explicitly because wallboxes may already be controlled by an energy manager such as evcc. If Home Assistant wrote charging current or phases at the same time, the two systems would overwrite each other.

While control is not allowed:

- all sensors and binary sensors keep updating;
- the `Charging current` number and the `Phases` select are not created;
- every EMS service except `set_ems_control_enabled` is rejected with an error and writes nothing;
- the [EMS keep-alive](#ems-keep-alive) does not run.

Leave the option off if another energy manager controls the Wallbox. Turn it on if Home Assistant should control charging.

When you allow control again, Home Assistant creates them again and restores their settings, such as entity ID, name, and area; entities you disabled yourself stay disabled.

## EMS controls

The number and select entities write the same EMS registers as the services below and can be used on dashboards or by tools such as evcc:

| Entity | Register | Values |
| --- | --- | --- |
| `Charging current` number | `0x00A2` | `0` pauses charging; otherwise `6` to `32` A in 1 A steps, or `6` to `16` A on an 11 kW Wallbox. `1` to `5` A and values that are not whole amperes are rejected with an error and nothing is written, as with the services. |
| `Phases` select | `0x00A1` | `Phase 1` or `3 Phases`. |

These entities only exist while control by Home Assistant is allowed. Every write from them first enables EMS control (`0x00A0`).

Turning off **Allow control by Home Assistant** writes nothing to the Wallbox and leaves EMS control as it is, so another energy manager such as evcc can take over. Home Assistant also stops the [EMS keep-alive](#ems-keep-alive). If no other system writes a new setpoint, what happens next depends on the EMS timeout:

- above `0 s`: the Wallbox switches to the timeout fallback phases and current once the timeout expires;
- `0 s`: the last setpoint written by Home Assistant stays in effect, including a paused charge.

To hand the Wallbox back to its own control, call `set_ems_control_enabled` with `enabled: false`.

After every write, from these entities or from the services, the integration reads the Wallbox again so the readback sensors update right away.

### EMS keep-alive

With an EMS timeout period above `0 s` (register `0x00A3`), the Wallbox falls back to the timeout fallback phases and current unless a setpoint is written again before the timeout expires. The integration does this automatically while control by Home Assistant is allowed and EMS control is enabled: it rewrites the current charging-current setpoint (`0x00A2`) every half timeout period, but never more often than every `5 s`. For example, it writes every `30 s` for a `60 s` timeout and every `5 s` for an `8 s` timeout. A timeout of `5 s` or less cannot be kept alive reliably.

With a timeout of `0 s`, or while control is not allowed, no keep-alive is written.

## EMS control services

These Home Assistant services write EMS setpoints to Modbus holding registers. Every service requires `device_id`, which selects the Wallbox device.

| Service | Register | Additional field and allowed values |
| --- | --- | --- |
| `set_ems_control_enabled` | `0x00A0` | `enabled`: `true` or `false` |
| `set_relay_matrix` | `0x00A1` | `value`: `phase_1` or `three_phases` |
| `set_charging_current` | `0x00A2` | `value`: `0` or `6` to `32` A in 1 A steps |
| `set_timeout_period` | `0x00A3` | `value`: `0` (off), `30`, `60`, `120`, `180`, `300`, or `600` seconds |
| `set_timeout_fallback_relay_matrix` | `0x00A4` | `value`: `phase_1` or `three_phases` |
| `set_timeout_fallback_current` | `0x00A5` | `value`: `0` or `6` to `32` A in 1 A steps |

`set_ems_control_enabled` is always available, even while control by Home Assistant is not allowed. `set_relay_matrix` and `set_charging_current` enable EMS control before writing the setpoint. While control by Home Assistant is not allowed, all other services are rejected with an error and write nothing. While EMS control is off, the timeout services are rejected with an error and write nothing.

Requests of `1` to `5 A` are rejected with an error for both the charging-current setpoint and timeout fallback, because the Wallbox cannot charge below `6 A`. Values that are not whole amperes, such as `6.5`, are rejected with an error instead of being rounded. For an 11 kW Wallbox, requests above `16 A` are rejected for both the charging-current setpoint and timeout fallback. A `0 A` value pauses charging and grants no charging current; it is accepted by both the charging-current setpoint and the timeout fallback. The timeout fallback relay-matrix sensor reports `phase_1`, `phase_2`, `phase_3`, or `three_phases`; the services only accept the values the register manual defines as supported.

Unsupported values, devices that are not a Kathrein Wallbox, and inactive Wallboxes are rejected with a validation error before anything is written. A failed register write is reported as an error.

Example service call to request `16 A` (replace the placeholder with the Wallbox's device ID; in the automation editor, pick the Wallbox from the device list instead):

```yaml
action: kathrein_wallbox.set_charging_current
data:
  device_id: "<device-id>"
  value: 16
```

These services write directly to the Wallbox. Check the phase selection, current, timeout, fallback behavior, and Wallbox rating before using them in automations. The integration does not write authentication tags or tariff registers.

## Use cases

- **Monitor charging and energy.** Follow charging state, power, and session energy, also read-only next to evcc or another energy manager. Add `Total energy` as an individual device in the Home Assistant energy dashboard (**Settings > Dashboards > Energy**) to track the Wallbox's consumption.
- **Get notified about faults.** Use the EVSE fault binary sensors to send a notification when the Wallbox reports a fault.
- **Control charging current and phases.** Set `Charging current` and `Phases` from dashboards, scripts, or automations.

## Automation examples

The examples use the default entity IDs of a Wallbox named `Kathrein Wallbox`; adjust them to the entity IDs on your device page. Replace `notify.mobile_app_phone` with your own notification action.

### Notify on a fault

The EVSE fault binary sensors may be disabled in the entity registry. Enable the ones you want to use on the device page first.

```yaml
alias: Wallbox fault
triggers:
  - trigger: state
    entity_id:
      - binary_sensor.kathrein_wallbox_relay_welded
      - binary_sensor.kathrein_wallbox_residual_dc_current
      - binary_sensor.kathrein_wallbox_internal_error
    to: "on"
actions:
  - action: notify.mobile_app_phone
    data:
      message: "Wallbox fault: {{ trigger.to_state.name }}"
```

### Notify when charging is completed

```yaml
alias: Wallbox charging completed
triggers:
  - trigger: state
    entity_id: sensor.kathrein_wallbox_charging_state
    from: charging_active
    to: charging_completed
actions:
  - action: notify.mobile_app_phone
    data:
      message: >-
        Charging completed:
        {{ states('sensor.kathrein_wallbox_energy_charged') }}
        {{ state_attr('sensor.kathrein_wallbox_energy_charged', 'unit_of_measurement') }}
        charged.
```

### Set the charging current by time of day

This example needs **Allow control by Home Assistant** turned on, see [Control by Home Assistant](#control-by-home-assistant). It charges with `16 A` at night and `6 A` during the day.

```yaml
alias: Wallbox charging current by time
triggers:
  - trigger: time
    at: "22:00:00"
    id: night
  - trigger: time
    at: "06:00:00"
    id: day
actions:
  - action: number.set_value
    target:
      entity_id: number.kathrein_wallbox_charging_current
    data:
      value: "{{ 16 if trigger.id == 'night' else 6 }}"
```

## Troubleshooting

| Symptom | Checks |
| --- | --- |
| Cannot connect during setup | Confirm the host, port, and unit ID; make sure the Modbus server is enabled in the Wallbox web interface under **Settings > Modbus TCP control** and the Home Assistant host can reach the Wallbox on the network. |
| Device is not supported | Confirm the device reports mapping version `0x0002` and a readable serial number. |
| Meter entities are unavailable | Meter data is optional. Check the meter diagnostics binary sensor and the reference ranges above. If the Wallbox has a meter that was not detected, reload the integration to repeat the check. |
| Repair issue about an invalid phase rotation | The Wallbox reports a line mapping marked as invalid phase rotation (L1-L3-L2, L2-L1-L3 or L3-L2-L1). Have the supply connection and the line mapping set during installation checked by a qualified electrician. The integration checks the line mapping only at startup; reload the integration or restart Home Assistant after the fix. |
| Need more information for a report | Download diagnostics from the Kathrein Wallbox config entry under **Settings > Devices & services** and attach them to an issue, after reviewing the data. |

## Compatibility and register notes

The integration uses local Modbus TCP and was developed against Register Mapping V1.5. The setup flow checks mapping version `0x0002`; this does not establish compatibility with every Wallbox model or firmware. Verify readings and write behavior on your specific device before relying on automated control.

The register manual describes FLOAT32 values as IEEE 754 but does not specify word order. The integration currently decodes them using big-endian word order; compare measurements with the Wallbox before relying on them. The manual describes register `0x005C` as energy in Wh. Session energy uses the UINT32 counter at `0x0069` and is also exposed in Wh.

## Diagnostics and privacy

Downloaded config-entry diagnostics include model and mapping information, meter availability, and register snapshots from the identity (including the line mapping `0x001A`), EVSE, meter, and session-energy blocks. Serial-number registers `0x0011`-`0x0018` are removed. EMS control registers and the authorization tag and charging session ID registers (`0x0070`-`0x0099`) are not included. Review diagnostics before sharing them publicly.

## Removing the integration

1. Open **Settings > Devices & services**, select **Kathrein Wallbox**, open the menu (⋮) of the entry, and choose **Delete**.
2. Optionally, remove **Kathrein Wallbox** in HACS (or delete `custom_components/kathrein_wallbox` for a manual installation).
3. Restart Home Assistant.

Removing the integration does not reset anything on the Wallbox. EMS control and the last setpoint stay as they were last written, see [EMS controls](#ems-controls). To hand the Wallbox back to its own control, call `set_ems_control_enabled` with `enabled: false` before removing the integration.

## Support

Please [open an issue](https://github.com/zomtec/hacs-kathrein-wallbox/issues) for bug reports or feature requests. Include your Home Assistant version, Wallbox model and firmware if known, and relevant diagnostics with personal or network details reviewed.

## Acknowledgments

This integration was created with substantial assistance from Claude, an AI assistant by Anthropic.

## License

Original project materials are licensed under the MIT License. The Kathrein brand graphics and the Modbus register manual (including its extracted text) are excluded and remain subject to their respective rights holders' terms. See [LICENSE](LICENSE) and [LICENSE-SCOPE.md](LICENSE-SCOPE.md) for the license and exclusions.

## Brand assets

The Home Assistant brand images are sourced from the official Kathrein website:

- Icon: [Kathrein favicon](https://www.kathrein-ds.com/wp-content/uploads/2026/04/kathrein_favicon.webp)
- Logo: [Kathrein Digital Systems](https://www.kathrein-ds.com/wp-content/uploads/2026/04/kathrein_logo_600px.webp)

Home Assistant shows these images on the integration and device pages.
