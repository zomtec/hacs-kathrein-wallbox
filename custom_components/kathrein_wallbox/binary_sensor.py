"""Binary sensor platform for Wallbox relays, faults and EMS control."""

from dataclasses import dataclass
from enum import IntFlag

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.components.binary_sensor.const import BinarySensorDeviceClass
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import CoordinatorGetter, KathreinWallboxEntity
from .model import ErrorState, RelayState

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class KathreinBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Wallbox binary sensor and how to read its state."""

    is_on_fn: CoordinatorGetter[bool | None]


def _flag_set(flags: IntFlag | None, flag: IntFlag) -> bool | None:
    """Return whether the flag is set in the decoded flag register."""
    if flags is None:
        return None
    return flag in flags


def _fault(key: str, flag: ErrorState) -> KathreinBinarySensorDescription:
    """Describe a fault bit of the EVSE error register."""
    return KathreinBinarySensorDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda c: _flag_set(c.device.evse.error_states, flag),
    )


def _relay(key: str, flag: RelayState) -> KathreinBinarySensorDescription:
    """Describe a phase relay bit of the EVSE relay state register."""
    return KathreinBinarySensorDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        is_on_fn=lambda c: _flag_set(c.device.evse.relay_state, flag),
    )


ENTITY_DESCRIPTIONS: tuple[KathreinBinarySensorDescription, ...] = (
    _fault("relay_welded", ErrorState.RELAY_WELDED),
    _fault("residual_dc_current", ErrorState.RESIDUAL_DC_CURRENT),
    _fault("socket_lock_error", ErrorState.SOCKET_LOCK_ERROR),
    _fault("charging_overcurrent", ErrorState.CHARGING_OVERCURRENT),
    _fault("ventilation_unavailable", ErrorState.VENTILATION_UNAVAILABLE),
    _fault("cp_short_circuit", ErrorState.CP_SHORT_CIRCUIT),
    _fault("cp_loop_broken", ErrorState.CP_LOOP_BROKEN),
    _fault("pp_short_circuit", ErrorState.PP_SHORT_CIRCUIT),
    _fault("internal_error", ErrorState.INTERNAL_ERROR),
    _relay("relay_l1", RelayState.RELAY_L1),
    _relay("relay_l2", RelayState.RELAY_L2),
    _relay("relay_l3", RelayState.RELAY_L3),
    KathreinBinarySensorDescription(
        key="ems_control",
        translation_key="ems_control",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: c.device.ems_control.is_enabled,
    ),
    KathreinBinarySensorDescription(
        key="meter_available",
        translation_key="meter_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: c.meter_detected,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Wallbox diagnostic binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        KathreinBinarySensor(coordinator, description)
        for description in ENTITY_DESCRIPTIONS
    )


class KathreinBinarySensor(KathreinWallboxEntity, BinarySensorEntity):
    """Expose a fault, relay, or availability state as a binary sensor."""

    entity_description: KathreinBinarySensorDescription

    def __init__(
        self,
        coordinator: KathreinCoordinator,
        description: KathreinBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return the state represented by this description."""
        return self.entity_description.is_on_fn(self.coordinator)
