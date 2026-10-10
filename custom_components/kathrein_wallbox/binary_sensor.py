"""Binary sensor platform for Wallbox relays and faults."""

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import CoordinatorGetter, KathreinWallboxEntity
from .model import EMS_CONTROL_ENABLED, ErrorState, RelayState


@dataclass(frozen=True, kw_only=True)
class KathreinBinarySensorDescription(BinarySensorEntityDescription):
    """Describe a Wallbox binary sensor and how to read its state."""

    is_on_fn: CoordinatorGetter[bool | None]


def _bit_set(register: int | None, mask: int) -> bool | None:
    """Return whether any bit of the mask is set in the register."""
    if register is None:
        return None
    return bool(register & mask)


def _fault(key: str, flag: ErrorState) -> KathreinBinarySensorDescription:
    """Describe a fault bit of the EVSE error register."""
    return KathreinBinarySensorDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: _bit_set(c.evse.error_states, flag),
    )


def _relay(key: str, flag: RelayState) -> KathreinBinarySensorDescription:
    """Describe a phase relay bit of the EVSE relay state register."""
    return KathreinBinarySensorDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: _bit_set(c.evse.relay_state, flag),
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
        key="ems_control_enabled",
        translation_key="ems_control_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: _bit_set(
            c.ems_control.control_register, EMS_CONTROL_ENABLED
        ),
    ),
    KathreinBinarySensorDescription(
        key="meter_available",
        translation_key="meter_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        is_on_fn=lambda c: c.meter_available,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddEntitiesCallback,
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
