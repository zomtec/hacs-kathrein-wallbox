"""Services for the Kathrein Wallbox integration."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import probatio
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .model import (
    EMS_CHARGING_PAUSED_MA,
    EMS_MAX_CHARGING_CURRENT_MA,
    EMS_MIN_CHARGING_CURRENT_MA,
    EMS_RELAY_MATRIX_OPTIONS,
    EMS_TIMEOUT_PERIODS_S,
    MAX_CURRENT_11_KW_MA,
    MILLIAMPERE_PER_AMPERE,
)

ATTR_ENABLED = "enabled"
ATTR_VALUE = "value"

SERVICE_SET_EMS_CONTROL_ENABLED = "set_ems_control_enabled"
SERVICE_SET_RELAY_MATRIX = "set_relay_matrix"
SERVICE_SET_CHARGING_CURRENT = "set_charging_current"
SERVICE_SET_TIMEOUT_PERIOD = "set_timeout_period"
SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX = "set_timeout_fallback_relay_matrix"
SERVICE_SET_TIMEOUT_FALLBACK_CURRENT = "set_timeout_fallback_current"

EMS_TIMEOUT_PERIOD_OPTIONS = {
    str(seconds): seconds for seconds in EMS_TIMEOUT_PERIODS_S
}


def _whole_amperes(value: Any) -> int:
    """Accept a whole number of amperes given as number or text."""
    try:
        amperes = float(value)
    except (TypeError, ValueError) as err:
        raise probatio.Invalid("expected a whole number of amperes") from err
    if not amperes.is_integer():
        raise probatio.Invalid("expected a whole number of amperes")
    return int(amperes)


def _milliamperes(amperes: int) -> int:
    """Convert a current in A to the mA register value."""
    return amperes * MILLIAMPERE_PER_AMPERE


EMS_CURRENT_AMPERES = probatio.All(
    _whole_amperes,
    probatio.Range(
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
        value_schema=probatio.In(list(EMS_RELAY_MATRIX_OPTIONS)),
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
        value_schema=probatio.In(list(EMS_TIMEOUT_PERIOD_OPTIONS)),
        to_register=EMS_TIMEOUT_PERIOD_OPTIONS.__getitem__,
    ),
    EmsSetpointService(
        name=SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
        field="timeout_fallback_relay_matrix",
        value_schema=probatio.In(list(EMS_RELAY_MATRIX_OPTIONS)),
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
    entry: KathreinConfigEntry | None = next(
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
) -> Callable[[ServiceCall], Coroutine[Any, Any, None]]:
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


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Wallbox EMS control services."""

    async def _async_set_ems_control_enabled(call: ServiceCall) -> None:
        """Enable or disable the EMS control register."""
        coordinator = _get_coordinator(hass, call.data[ATTR_DEVICE_ID])
        await coordinator.async_set_ems_control(call.data[ATTR_ENABLED])

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_EMS_CONTROL_ENABLED,
        _async_set_ems_control_enabled,
        schema=probatio.Schema(
            {
                probatio.Required(ATTR_DEVICE_ID): str,
                probatio.Required(ATTR_ENABLED): bool,
            }
        ),
    )
    for service in EMS_SETPOINT_SERVICES:
        hass.services.async_register(
            DOMAIN,
            service.name,
            _setpoint_handler(hass, service),
            schema=probatio.Schema(
                {
                    probatio.Required(ATTR_DEVICE_ID): str,
                    probatio.Required(ATTR_VALUE): service.value_schema,
                }
            ),
        )
