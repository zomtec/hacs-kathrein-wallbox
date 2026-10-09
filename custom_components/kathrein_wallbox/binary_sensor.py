"""Binary sensor platform for Wallbox relays and faults."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KathreinCoordinator, WallboxRuntimeData
from .entity import KathreinWallboxEntity

FAULTS = (
    ("relay_welded", 0x0001),
    ("residual_dc_current", 0x0002),
    ("socket_lock_error", 0x0004),
    ("charging_overcurrent", 0x0008),
    ("ventilation_unavailable", 0x0010),
    ("cp_short_circuit", 0x0020),
    ("cp_loop_broken", 0x0040),
    ("pp_short_circuit", 0x0080),
    ("internal_error", 0x8000),
)
RELAYS = (
    ("relay_l1", 0x0001),
    ("relay_l2", 0x0002),
    ("relay_l3", 0x0004),
)

ENTITY_DESCRIPTIONS = tuple(
    BinarySensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.PROBLEM,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for key, _ in FAULTS
) + tuple(
    BinarySensorEntityDescription(
        key=key,
        translation_key=key,
        device_class=BinarySensorDeviceClass.POWER,
        entity_category=EntityCategory.DIAGNOSTIC,
    )
    for key, _ in RELAYS
) + (
    BinarySensorEntityDescription(
        key="ems_control_enabled",
        translation_key="ems_control_enabled",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="meter_available",
        translation_key="meter_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[WallboxRuntimeData],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wallbox diagnostic binary sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        KathreinBinarySensor(coordinator, description)
        for description in ENTITY_DESCRIPTIONS
    )


class KathreinBinarySensor(KathreinWallboxEntity, BinarySensorEntity):
    """Expose a fault bit or relay bit as a binary sensor."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: KathreinCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        bitmask = dict((*FAULTS, *RELAYS))
        self._register_bit = bitmask.get(description.key)
        self._is_fault = description.key in dict(FAULTS)

    @property
    def is_on(self) -> bool | None:
        """Return the state represented by this register bit."""
        if self.entity_description.key == "ems_control_enabled":
            register = self.coordinator.ems_control.control_register
            return None if register is None else bool(register & 0x8000)
        if self.entity_description.key == "meter_available":
            return self.coordinator.meter_available
        register = (
            self.coordinator.evse.error_states
            if self._is_fault
            else self.coordinator.evse.relay_state
        )
        if register is None or self._register_bit is None:
            return None
        return bool(register & self._register_bit)