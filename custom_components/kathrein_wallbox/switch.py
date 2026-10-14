"""Switch platform for Kathrein Wallbox EMS control."""

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import KathreinWallboxEntity
from .model import EMS_CONTROL_DISABLED, EMS_CONTROL_ENABLED

PARALLEL_UPDATES = 1

EMS_CONTROL_DESCRIPTION = SwitchEntityDescription(
    key="ems_control",
    translation_key="ems_control",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EMS control switch."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([KathreinEmsControlSwitch(coordinator)])


class KathreinEmsControlSwitch(KathreinWallboxEntity, SwitchEntity):
    """Enable or disable EMS control of the Wallbox."""

    def __init__(self, coordinator: KathreinCoordinator) -> None:
        super().__init__(coordinator, EMS_CONTROL_DESCRIPTION.key)
        self.entity_description = EMS_CONTROL_DESCRIPTION

    @property
    def is_on(self) -> bool | None:
        """Return whether the EMS control bit is set."""
        register = self.coordinator.ems_control.control_register
        if register is None:
            return None
        return bool(register & EMS_CONTROL_ENABLED)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable EMS control."""
        await self.coordinator.async_write_ems("control_register", EMS_CONTROL_ENABLED)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable EMS control."""
        await self.coordinator.async_write_ems("control_register", EMS_CONTROL_DISABLED)
