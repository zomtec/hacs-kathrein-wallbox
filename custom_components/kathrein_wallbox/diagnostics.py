"""Diagnostics for the Kathrein Wallbox integration."""

from homeassistant.core import HomeAssistant
from modbus_connection import ModbusError

from .coordinator import KathreinConfigEntry
from .model import (
    COMPONENT_METER,
    COMPONENT_SESSION_ENERGY,
    SERIAL_ADDRESS,
    SERIAL_REGISTER_COUNT,
)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
) -> dict[str, object]:
    """Return the raw mapped registers without exposing the serial number."""
    coordinator = entry.runtime_data.coordinator
    try:
        identity_registers = await coordinator.device.identity.async_read_raw()
        evse_registers = await coordinator.device.evse.async_read_raw()
    except ModbusError:
        return {"error": "Unable to read Wallbox registers"}

    registers: dict[str, dict[int, int | bool]] = {}
    for component_registers in (identity_registers, evse_registers):
        for register_type, values in component_registers.items():
            registers.setdefault(register_type, {}).update(values)

    try:
        meter_registers = await coordinator.device.meter.async_read_raw()
    except ModbusError:
        meter_registers = {}
    try:
        session_registers = await coordinator.device.session_energy.async_read_raw()
    except ModbusError:
        session_registers = {}
    for component_registers in (meter_registers, session_registers):
        for register_type, values in component_registers.items():
            registers.setdefault(register_type, {}).update(values)

    holding = registers.get("holding", {})
    for address in range(SERIAL_ADDRESS, SERIAL_ADDRESS + SERIAL_REGISTER_COUNT):
        holding.pop(address, None)

    return {
        "model": coordinator.device.identity.device_type,
        "mapping_version": coordinator.device.identity.mapping_version,
        "meter_available": COMPONENT_METER in coordinator.data.updated,
        "session_energy_available": COMPONENT_SESSION_ENERGY
        in coordinator.data.updated,
        "registers": registers,
    }
