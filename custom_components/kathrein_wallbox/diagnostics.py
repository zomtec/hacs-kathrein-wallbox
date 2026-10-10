"""Diagnostics for the Kathrein Wallbox integration."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from modbus_connection import ModbusError

from .coordinator import WallboxRuntimeData


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry[WallboxRuntimeData],
) -> dict[str, object]:
    """Return the raw mapped registers without exposing the serial number."""
    coordinator = entry.runtime_data.coordinator
    try:
        identity_registers = await coordinator.identity.async_read_raw()
        evse_registers = await coordinator.evse.async_read_raw()
    except ModbusError:
        return {"error": "Unable to read Wallbox registers"}

    registers: dict[str, dict[int, int | bool]] = {}
    for component_registers in (identity_registers, evse_registers):
        for register_type, values in component_registers.items():
            registers.setdefault(register_type, {}).update(values)

    try:
        meter_registers = await coordinator.meter.async_read_raw()
    except ModbusError:
        meter_registers = {}
    try:
        session_registers = await coordinator.session_energy.async_read_raw()
    except ModbusError:
        session_registers = {}
    for component_registers in (meter_registers, session_registers):
        for register_type, values in component_registers.items():
            registers.setdefault(register_type, {}).update(values)

    holding = registers.get("holding", {})
    for address in range(0x0011, 0x0019):
        holding.pop(address, None)

    return {
        "model": coordinator.identity.device_type,
        "mapping_version": coordinator.identity.mapping_version,
        "meter_available": coordinator.meter_available,
        "session_energy_available": coordinator.session_energy_available,
        "registers": registers,
    }
