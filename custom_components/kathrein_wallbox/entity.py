"""Common entity base for Kathrein Wallbox platforms."""

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KathreinCoordinator


class KathreinWallboxEntity(CoordinatorEntity[KathreinCoordinator]):
    """Represent an entity backed by the shared Wallbox coordinator."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: KathreinCoordinator, key: str) -> None:
        super().__init__(coordinator)
        serial = coordinator.identity.serial or "unknown"
        self._attr_unique_id = f"{serial}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer="Kathrein",
            model=coordinator.identity.device_type or "Wallbox",
            serial_number=coordinator.identity.serial,
            name="Kathrein Wallbox",
        )
