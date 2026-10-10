"""Kathrein Wallbox integration setup."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.components.modbus import async_get_unit
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from modbus_connection import ModbusError, ModbusTcpParams

from .const import CONF_UNIT_ID, DOMAIN, PLATFORMS, get_scan_interval
from .coordinator import KathreinConfigEntry, KathreinCoordinator, WallboxRuntimeData
from .model import (
    EMS_CHARGING_CURRENTS_MA,
    EMS_CONTROL_DISABLED,
    EMS_CONTROL_ENABLED,
    EMS_TIMEOUT_PERIODS_S,
    MAX_CURRENT_11_KW_MA,
    MILLIAMPERE_PER_AMPERE,
    RelayMatrix,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_ENTRY_ID = "entry_id"
ATTR_ENABLED = "enabled"
ATTR_VALUE = "value"

SERVICE_SET_EMS_CONTROL_ENABLED = "set_ems_control_enabled"
SERVICE_SET_RELAY_MATRIX = "set_relay_matrix"
SERVICE_SET_CHARGING_CURRENT = "set_charging_current"
SERVICE_SET_TIMEOUT_PERIOD = "set_timeout_period"
SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX = "set_timeout_fallback_relay_matrix"
SERVICE_SET_TIMEOUT_FALLBACK_CURRENT = "set_timeout_fallback_current"

# Service option -> register value; the manual reserves phases 2 and 3 for future use.
EMS_RELAY_MATRIX_OPTIONS = {
    "phase_1": RelayMatrix.PHASE_1,
    "three_phases": RelayMatrix.THREE_PHASES,
}
EMS_CHARGING_CURRENT_OPTIONS = {
    str(current_ma // MILLIAMPERE_PER_AMPERE): current_ma
    for current_ma in EMS_CHARGING_CURRENTS_MA
}
EMS_TIMEOUT_PERIOD_OPTIONS = {
    str(seconds): seconds for seconds in EMS_TIMEOUT_PERIODS_S
}


@dataclass(frozen=True, kw_only=True)
class EmsSetpointService:
    """Describe a service that writes one EMS setpoint register."""

    name: str
    field: str
    options: Mapping[str, int]
    is_current: bool = False


EMS_SETPOINT_SERVICES = (
    EmsSetpointService(
        name=SERVICE_SET_RELAY_MATRIX,
        field="relay_matrix",
        options=EMS_RELAY_MATRIX_OPTIONS,
    ),
    EmsSetpointService(
        name=SERVICE_SET_CHARGING_CURRENT,
        field="charging_current",
        options=EMS_CHARGING_CURRENT_OPTIONS,
        is_current=True,
    ),
    EmsSetpointService(
        name=SERVICE_SET_TIMEOUT_PERIOD,
        field="timeout_period",
        options=EMS_TIMEOUT_PERIOD_OPTIONS,
    ),
    EmsSetpointService(
        name=SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
        field="timeout_fallback_relay_matrix",
        options=EMS_RELAY_MATRIX_OPTIONS,
    ),
    EmsSetpointService(
        name=SERVICE_SET_TIMEOUT_FALLBACK_CURRENT,
        field="timeout_fallback_current",
        options=EMS_CHARGING_CURRENT_OPTIONS,
        is_current=True,
    ),
)


def _get_coordinator(hass: HomeAssistant, entry_id: str) -> KathreinCoordinator:
    """Return the coordinator of a loaded Wallbox config entry."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"entry_id": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"title": entry.title},
        )
    return entry.runtime_data.coordinator


async def _async_write_ems_register(
    coordinator: KathreinCoordinator, field: str, value: int
) -> None:
    """Write an EMS control field and report device failures."""
    try:
        await coordinator.ems_control.write(field, value)
    except ModbusError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="write_failed",
            translation_placeholders={"error": str(err)},
        ) from err


def _setpoint_handler(
    hass: HomeAssistant, service: EmsSetpointService
) -> Callable[[ServiceCall], Awaitable[None]]:
    """Create the handler writing one validated setpoint."""

    async def _async_handle(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data[ATTR_ENTRY_ID])
        value = service.options[call.data[ATTR_VALUE]]
        if (
            service.is_current
            and coordinator.identity.is_11_kw
            and value > MAX_CURRENT_11_KW_MA
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="current_limit_11_kw",
                translation_placeholders={
                    "max_current": str(MAX_CURRENT_11_KW_MA // MILLIAMPERE_PER_AMPERE)
                },
            )
        await _async_write_ems_register(coordinator, service.field, value)

    return _async_handle


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Wallbox EMS control services."""

    async def _async_set_ems_control_enabled(call: ServiceCall) -> None:
        """Enable or disable the EMS control register."""
        coordinator = _get_coordinator(hass, call.data[ATTR_ENTRY_ID])
        value = EMS_CONTROL_ENABLED if call.data[ATTR_ENABLED] else EMS_CONTROL_DISABLED
        await _async_write_ems_register(coordinator, "control_register", value)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_EMS_CONTROL_ENABLED,
        _async_set_ems_control_enabled,
        schema=vol.Schema(
            {vol.Required(ATTR_ENTRY_ID): str, vol.Required(ATTR_ENABLED): bool}
        ),
    )
    for service in EMS_SETPOINT_SERVICES:
        hass.services.async_register(
            DOMAIN,
            service.name,
            _setpoint_handler(hass, service),
            schema=vol.Schema(
                {
                    vol.Required(ATTR_ENTRY_ID): str,
                    vol.Required(ATTR_VALUE): vol.In(list(service.options)),
                }
            ),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: KathreinConfigEntry) -> bool:
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


async def async_unload_entry(hass: HomeAssistant, entry: KathreinConfigEntry) -> bool:
    """Unload platforms for a Wallbox config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
