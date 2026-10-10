"""Common entity base for Kathrein Wallbox platforms."""

from collections.abc import Callable

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEVICE_NAME, DOMAIN, MANUFACTURER
from .coordinator import KathreinCoordinator

type CoordinatorGetter[T] = Callable[[KathreinCoordinator], T]


def always_available(coordinator: KathreinCoordinator) -> bool:
    """Default availability rule for entities without an optional register block."""
    return True


class KathreinWallboxEntity(CoordinatorEntity[KathreinCoordinator]):
    """Represent an entity backed by the shared Wallbox coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KathreinCoordinator, key: str) -> None:
        super().__init__(coordinator)
        serial = coordinator.identity.serial
        # The coordinator refuses to publish data without a serial number.
        assert serial is not None
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer=MANUFACTURER,
            model=coordinator.identity.device_type,
            serial_number=serial,
            name=DEVICE_NAME,
        )
