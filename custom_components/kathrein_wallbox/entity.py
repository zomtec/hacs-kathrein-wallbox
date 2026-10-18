"""Common entity base for Kathrein Wallbox platforms."""

from collections.abc import Callable

from homeassistant.const import CONF_HOST, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from yarl import URL

from .const import DEVICE_NAME, DOMAIN, MANUFACTURER
from .coordinator import KathreinCoordinator

type CoordinatorGetter[T] = Callable[[KathreinCoordinator], T]


def wallbox_unique_id(serial: str, key: str) -> str:
    """Build the unique ID of a Wallbox entity from the serial number and key."""
    return f"{serial}_{key}"


class KathreinWallboxEntity(CoordinatorEntity[KathreinCoordinator]):
    """Represent an entity backed by the shared Wallbox coordinator."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: KathreinCoordinator,
        key: str,
        component: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        # The optional component this entity reads; essential ones fail the poll.
        self._component = component
        serial = coordinator.serial
        self._attr_unique_id = wallbox_unique_id(serial, key)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, serial)},
            manufacturer=MANUFACTURER,
            model=coordinator.device.identity.device_type,
            model_id=coordinator.device.identity.device_number,
            serial_number=serial,
            name=DEVICE_NAME,
            # The Wallbox web interface is served on the Modbus host.
            configuration_url=str(
                URL.build(scheme="http", host=coordinator.config_entry.data[CONF_HOST])
            ),
        )

    @property
    def available(self) -> bool:
        """Report unavailable while the optional component did not answer the poll."""
        return super().available and (
            self._component is None or self._component in self.coordinator.data.updated
        )


@callback
def async_setup_control_entity(
    hass: HomeAssistant,
    coordinator: KathreinCoordinator,
    async_add_entities: AddConfigEntryEntitiesCallback,
    platform: Platform,
    key: str,
    create_entity: CoordinatorGetter[KathreinWallboxEntity],
) -> None:
    """Add a control entity while control is allowed, otherwise remove its entry."""
    if coordinator.control_allowed:
        async_add_entities([create_entity(coordinator)])
        return
    registry = er.async_get(hass)
    unique_id = wallbox_unique_id(coordinator.serial, key)
    if entity_id := registry.async_get_entity_id(platform, DOMAIN, unique_id):
        registry.async_remove(entity_id)
