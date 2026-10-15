"""Kathrein Wallbox integration setup."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.components.modbus import async_get_unit
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType
from modbus_connection import ModbusTcpParams

from .const import CONF_UNIT_ID, DOMAIN, PLATFORMS, get_scan_interval
from .coordinator import KathreinConfigEntry, KathreinCoordinator, WallboxRuntimeData
from .entity import wallbox_unique_id
from .model import (
    EMS_CHARGING_PAUSED_MA,
    EMS_MAX_CHARGING_CURRENT_MA,
    EMS_MIN_CHARGING_CURRENT_MA,
    EMS_RELAY_MATRIX_OPTIONS,
    EMS_TIMEOUT_PERIODS_S,
    MAX_CURRENT_11_KW_MA,
    MILLIAMPERE_PER_AMPERE,
)
from .number import CHARGING_CURRENT_DESCRIPTION
from .select import RELAY_MATRIX_DESCRIPTION

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ATTR_DEVICE_ID = "device_id"
ATTR_ENABLED = "enabled"
ATTR_VALUE = "value"

SERVICE_SET_EMS_CONTROL_ENABLED = "set_ems_control_enabled"
SERVICE_SET_RELAY_MATRIX = "set_relay_matrix"
SERVICE_SET_CHARGING_CURRENT = "set_charging_current"
SERVICE_SET_TIMEOUT_PERIOD = "set_timeout_period"
SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX = "set_timeout_fallback_relay_matrix"
SERVICE_SET_TIMEOUT_FALLBACK_CURRENT = "set_timeout_fallback_current"

CONTROL_ENTITY_KEYS = (
    CHARGING_CURRENT_DESCRIPTION.key,
    RELAY_MATRIX_DESCRIPTION.key,
)

EMS_TIMEOUT_PERIOD_OPTIONS = {
    str(seconds): seconds for seconds in EMS_TIMEOUT_PERIODS_S
}


def _whole_amperes(value: Any) -> int:
    """Accept a whole number of amperes given as number or text."""
    try:
        amperes = float(value)
    except (TypeError, ValueError) as err:
        raise vol.Invalid("expected a whole number of amperes") from err
    if not amperes.is_integer():
        raise vol.Invalid("expected a whole number of amperes")
    return int(amperes)


def _milliamperes(amperes: int) -> int:
    """Convert a current in A to the mA register value."""
    return amperes * MILLIAMPERE_PER_AMPERE


EMS_CURRENT_AMPERES = vol.All(
    _whole_amperes,
    vol.Range(
        min=EMS_CHARGING_PAUSED_MA // MILLIAMPERE_PER_AMPERE,
        max=EMS_MAX_CHARGING_CURRENT_MA // MILLIAMPERE_PER_AMPERE,
    ),
)


@dataclass(frozen=True, kw_only=True)
class EmsSetpointService:
    """Describe a service that writes one EMS setpoint register."""

    name: str
    field: str
    value_schema: Callable[[Any], Any]
    to_register: Callable[[Any], int]
    is_current: bool = False
    enables_ems: bool = False


EMS_SETPOINT_SERVICES = (
    EmsSetpointService(
        name=SERVICE_SET_RELAY_MATRIX,
        field="relay_matrix",
        value_schema=vol.In(list(EMS_RELAY_MATRIX_OPTIONS)),
        to_register=EMS_RELAY_MATRIX_OPTIONS.__getitem__,
        enables_ems=True,
    ),
    EmsSetpointService(
        name=SERVICE_SET_CHARGING_CURRENT,
        field="charging_current",
        value_schema=EMS_CURRENT_AMPERES,
        to_register=_milliamperes,
        is_current=True,
        enables_ems=True,
    ),
    EmsSetpointService(
        name=SERVICE_SET_TIMEOUT_PERIOD,
        field="timeout_period",
        value_schema=vol.In(list(EMS_TIMEOUT_PERIOD_OPTIONS)),
        to_register=EMS_TIMEOUT_PERIOD_OPTIONS.__getitem__,
    ),
    EmsSetpointService(
        name=SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
        field="timeout_fallback_relay_matrix",
        value_schema=vol.In(list(EMS_RELAY_MATRIX_OPTIONS)),
        to_register=EMS_RELAY_MATRIX_OPTIONS.__getitem__,
    ),
    EmsSetpointService(
        name=SERVICE_SET_TIMEOUT_FALLBACK_CURRENT,
        field="timeout_fallback_current",
        value_schema=EMS_CURRENT_AMPERES,
        to_register=_milliamperes,
        is_current=True,
    ),
)


def _get_coordinator(hass: HomeAssistant, device_id: str) -> KathreinCoordinator:
    """Return the coordinator of the loaded config entry behind a Wallbox device."""
    device = dr.async_get(hass).async_get(device_id)
    entries = (
        hass.config_entries.async_get_entry(entry_id)
        for entry_id in (device.config_entries if device else ())
    )
    entry = next(
        (entry for entry in entries if entry is not None and entry.domain == DOMAIN),
        None,
    )
    if entry is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"title": entry.title},
        )
    return entry.runtime_data.coordinator


def _validate_ems_enabled(coordinator: KathreinCoordinator) -> None:
    """Reject EMS timeout settings while EMS control is off."""
    if not coordinator.ems_control.is_enabled:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="ems_control_disabled",
        )


def _validate_ems_current(coordinator: KathreinCoordinator, current_ma: int) -> None:
    """Reject EMS currents the Wallbox cannot charge with."""
    if EMS_CHARGING_PAUSED_MA < current_ma < EMS_MIN_CHARGING_CURRENT_MA:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="current_below_minimum",
            translation_placeholders={
                "min_current": str(
                    EMS_MIN_CHARGING_CURRENT_MA // MILLIAMPERE_PER_AMPERE
                )
            },
        )
    if coordinator.identity.is_11_kw and current_ma > MAX_CURRENT_11_KW_MA:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="current_limit_11_kw",
            translation_placeholders={
                "max_current": str(MAX_CURRENT_11_KW_MA // MILLIAMPERE_PER_AMPERE)
            },
        )


def _setpoint_handler(
    hass: HomeAssistant, service: EmsSetpointService
) -> Callable[[ServiceCall], Awaitable[None]]:
    """Create the handler writing one validated setpoint."""

    async def _async_handle(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass, call.data[ATTR_DEVICE_ID])
        coordinator.validate_control_allowed()
        if not service.enables_ems:
            _validate_ems_enabled(coordinator)
        value = service.to_register(call.data[ATTR_VALUE])
        if service.is_current:
            _validate_ems_current(coordinator, value)
        await coordinator.async_write_ems(
            service.field, value, enable_ems=service.enables_ems
        )

    return _async_handle


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the Wallbox EMS control services."""

    async def _async_set_ems_control_enabled(call: ServiceCall) -> None:
        """Enable or disable the EMS control register."""
        coordinator = _get_coordinator(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_set_ems_control(call.data[ATTR_ENABLED])

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_EMS_CONTROL_ENABLED,
        _async_set_ems_control_enabled,
        schema=vol.Schema(
            {vol.Required(ATTR_DEVICE_ID): str, vol.Required(ATTR_ENABLED): bool}
        ),
    )
    for service in EMS_SETPOINT_SERVICES:
        hass.services.async_register(
            DOMAIN,
            service.name,
            _setpoint_handler(hass, service),
            schema=vol.Schema(
                {
                    vol.Required(ATTR_DEVICE_ID): str,
                    vol.Required(ATTR_VALUE): service.value_schema,
                }
            ),
        )
    return True


@callback
def _async_sync_control_entities(
    hass: HomeAssistant, entry: KathreinConfigEntry, serial: str, allowed: bool
) -> None:
    """Disable control entities unless control is allowed, sparing user choices."""
    registry = er.async_get(hass)
    control_unique_ids = {wallbox_unique_id(serial, key) for key in CONTROL_ENTITY_KEYS}
    by_integration = er.RegistryEntryDisabler.INTEGRATION
    current, target = (by_integration, None) if allowed else (None, by_integration)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity_entry.unique_id in control_unique_ids
            and entity_entry.disabled_by is current
        ):
            registry.async_update_entity(entity_entry.entity_id, disabled_by=target)


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
    serial = coordinator.identity.serial
    # The coordinator refuses to publish data without a serial number.
    assert serial is not None
    _async_sync_control_entities(hass, entry, serial, coordinator.control_allowed)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KathreinConfigEntry) -> bool:
    """Unload platforms for a Wallbox config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
