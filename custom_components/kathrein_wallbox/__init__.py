"""Kathrein Wallbox integration setup."""

import inspect

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.components.modbus import async_get_unit
from modbus_connection import ModbusTcpParams

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_UNIT_ID,
    DOMAIN,
    PLATFORMS,
    get_scan_interval,
)
from .coordinator import KathreinCoordinator, WallboxRuntimeData

SERVICE_SET_EMS_CONTROL_ENABLED = "set_ems_control_enabled"
SERVICE_SET_RELAY_MATRIX = "set_relay_matrix"
SERVICE_SET_CHARGING_CURRENT = "set_charging_current"
SERVICE_SET_TIMEOUT_PERIOD = "set_timeout_period"
SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX = "set_timeout_fallback_relay_matrix"
SERVICE_SET_TIMEOUT_FALLBACK_CURRENT = "set_timeout_fallback_current"

EMS_CONTROL_VALID_VALUES = {
    "relay_matrix": {1: "Phase 1", 2: "Phase 2", 4: "Phase 3", 7: "3 Phases"},
    "charging_current": {6000: "6 A", 8000: "8 A", 10000: "10 A", 12000: "12 A", 16000: "16 A", 20000: "20 A", 24000: "24 A", 32000: "32 A"},
    "timeout_period": {0: "Off", 30: "30 s", 60: "60 s", 120: "2 min", 180: "3 min", 300: "5 min", 600: "10 min"},
    "timeout_fallback_relay_matrix": {1: "Phase 1", 2: "Phase 2", 4: "Phase 3", 7: "3 Phases"},
    "timeout_fallback_current": {0: "Off", 6000: "6 A", 8000: "8 A", 10000: "10 A", 12000: "12 A", 16000: "16 A", 20000: "20 A", 24000: "24 A", 32000: "32 A"},
}
EMS_RELAY_MATRIX_OPTIONS = {
    "line_1": 1,
    "line_2": 2,
    "line_3": 4,
    "three_lines": 7,
}
EMS_CHARGING_CURRENT_OPTIONS = {
    str(current_ma // 1000): current_ma
    for current_ma in EMS_CONTROL_VALID_VALUES["charging_current"]
}
EMS_TIMEOUT_FALLBACK_CURRENT_OPTIONS = {
    "0": 0,
    **EMS_CHARGING_CURRENT_OPTIONS,
}


async def _async_write_modbus_register(unit, address: int, value: int) -> None:
    """Write a register through the ModbusUnit implementation, tolerating API variations."""
    method_names = (
        "write_register",
        "write_holding_register",
        "async_write_register",
        "async_write_holding_register",
        "write_registers",
        "write_holding_registers",
        "async_write_registers",
        "async_write_holding_registers",
    )
    for method_name in method_names:
        method = getattr(unit, method_name, None)
        if method is None:
            continue
        try:
            result = method(address, value)
            if inspect.isawaitable(result):
                await result
            return
        except TypeError:
            try:
                result = method(address, [value])
                if inspect.isawaitable(result):
                    await result
                return
            except TypeError:
                continue
    raise HomeAssistantError(
        f"Modbus client for {address} does not expose a supported write method."
    )


async def _async_handle_write_register(
    hass: HomeAssistant,
    call: ServiceCall,
    register_address: int,
    allowed_values: dict[int, str],
    value_mapping: dict[str, int] | None = None,
) -> None:
    """Validate the requested value against the supported EMS setpoint values and write it."""
    raw_value = call.data["value"]
    if value_mapping is None:
        value = int(raw_value)
    else:
        try:
            value = value_mapping[raw_value]
        except KeyError as err:
            raise HomeAssistantError(f"Unsupported EMS value {raw_value}.") from err
    if value not in allowed_values:
        raise HomeAssistantError(
            f"Unsupported EMS value {value}. Allowed values: {sorted(allowed_values)}"
        )

    entry_id = call.data["entry_id"]
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise HomeAssistantError(f"No Kathrein Wallbox config entry found for {entry_id}.")

    coordinator = entry.runtime_data.coordinator
    if (
        register_address in (0x00A2, 0x00A5)
        and coordinator.identity.is_11_kw
        and value > 16000
    ):
        raise HomeAssistantError(
            "11 kW Wallboxes support a maximum EMS charging current of 16 A."
        )
    await _async_write_modbus_register(coordinator.unit, register_address, value)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the Wallbox EMS control services once."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_EMS_CONTROL_ENABLED):
        return True

    async def _async_set_ems_control_enabled(call: ServiceCall) -> None:
        """Enable or disable the EMS control register."""
        value = 0x8000 if call.data["enabled"] else 0
        entry_id = call.data["entry_id"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            raise HomeAssistantError(f"No Kathrein Wallbox config entry found for {entry_id}.")
        coordinator = entry.runtime_data.coordinator
        await _async_write_modbus_register(coordinator.unit, 0x00A0, value)

    async def _async_set_relay_matrix(call: ServiceCall) -> None:
        """Set the relay matrix for the EMS control register."""
        await _async_handle_write_register(
            hass,
            call,
            0x00A1,
            EMS_CONTROL_VALID_VALUES["relay_matrix"],
            EMS_RELAY_MATRIX_OPTIONS,
        )

    async def _async_set_charging_current(call: ServiceCall) -> None:
        """Set the EMS charging current setpoint."""
        await _async_handle_write_register(
            hass,
            call,
            0x00A2,
            EMS_CONTROL_VALID_VALUES["charging_current"],
            EMS_CHARGING_CURRENT_OPTIONS,
        )

    async def _async_set_timeout_period(call: ServiceCall) -> None:
        """Set the timeout period for the EMS charge current override."""
        await _async_handle_write_register(hass, call, 0x00A3, EMS_CONTROL_VALID_VALUES["timeout_period"])

    async def _async_set_timeout_fallback_relay_matrix(call: ServiceCall) -> None:
        """Set the timeout fallback relay matrix."""
        await _async_handle_write_register(
            hass,
            call,
            0x00A4,
            EMS_CONTROL_VALID_VALUES["timeout_fallback_relay_matrix"],
            EMS_RELAY_MATRIX_OPTIONS,
        )

    async def _async_set_timeout_fallback_current(call: ServiceCall) -> None:
        """Set the timeout fallback current."""
        await _async_handle_write_register(
            hass,
            call,
            0x00A5,
            EMS_CONTROL_VALID_VALUES["timeout_fallback_current"],
            EMS_TIMEOUT_FALLBACK_CURRENT_OPTIONS,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_EMS_CONTROL_ENABLED,
        _async_set_ems_control_enabled,
        schema=vol.Schema({vol.Required("entry_id"): str, vol.Required("enabled"): bool}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_RELAY_MATRIX,
        _async_set_relay_matrix,
        schema=vol.Schema({
            vol.Required("entry_id"): str,
            vol.Required("value"): vol.In(EMS_RELAY_MATRIX_OPTIONS),
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CHARGING_CURRENT,
        _async_set_charging_current,
        schema=vol.Schema({
            vol.Required("entry_id"): str,
            vol.Required("value"): vol.In(EMS_CHARGING_CURRENT_OPTIONS),
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TIMEOUT_PERIOD,
        _async_set_timeout_period,
        schema=vol.Schema({
            vol.Required("entry_id"): str,
            vol.Required("value"): vol.In(sorted(str(value) for value in EMS_CONTROL_VALID_VALUES["timeout_period"])),
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
        _async_set_timeout_fallback_relay_matrix,
        schema=vol.Schema({
            vol.Required("entry_id"): str,
            vol.Required("value"): vol.In(EMS_RELAY_MATRIX_OPTIONS),
        }),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TIMEOUT_FALLBACK_CURRENT,
        _async_set_timeout_fallback_current,
        schema=vol.Schema({
            vol.Required("entry_id"): str,
            vol.Required("value"): vol.In(EMS_TIMEOUT_FALLBACK_CURRENT_OPTIONS),
        }),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Wallbox config entry."""
    params = ModbusTcpParams(
        host=entry.data[CONF_HOST],
        port=int(entry.data[CONF_PORT]),
    )
    unit = async_get_unit(hass, entry, params, int(entry.data[CONF_UNIT_ID]))
    coordinator = KathreinCoordinator(
        hass,
        entry,
        unit,
        update_interval=get_scan_interval(entry),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = WallboxRuntimeData(coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload platforms for a Wallbox config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)