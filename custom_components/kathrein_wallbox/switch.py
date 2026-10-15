"""Switch platform for Kathrein Wallbox EMS control."""

from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import KathreinWallboxEntity
from .model import EMS_CONTROL_DISABLED, EMS_CONTROL_ENABLED

PARALLEL_UPDATES = 1

EMS_CONTROL_DESCRIPTION = SwitchEntityDescription(
    key="ems_control",
    translation_key="ems_control",
)

EMS_KEEP_ALIVE_DESCRIPTION = SwitchEntityDescription(
    key="ems_keep_alive",
    translation_key="ems_keep_alive",
    entity_category=EntityCategory.CONFIG,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EMS control and keep-alive switches."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        [
            KathreinEmsControlSwitch(coordinator),
            KathreinEmsKeepAliveSwitch(coordinator),
        ]
    )


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


class KathreinEmsKeepAliveSwitch(KathreinWallboxEntity, SwitchEntity, RestoreEntity):
    """Let the integration reset the EMS timeout by rewriting the setpoint."""

    def __init__(self, coordinator: KathreinCoordinator) -> None:
        super().__init__(coordinator, EMS_KEEP_ALIVE_DESCRIPTION.key)
        self.entity_description = EMS_KEEP_ALIVE_DESCRIPTION

    async def async_added_to_hass(self) -> None:
        """Restore a keep-alive the user turned on before a restart."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state == STATE_ON:
            self.coordinator.async_set_keep_alive(True)

    @property
    def available(self) -> bool:
        """Allow control only while the Wallbox has an EMS timeout configured."""
        return super().available and self.coordinator.keep_alive_supported

    @property
    def is_on(self) -> bool:
        """Return whether the keep-alive runs."""
        return self.coordinator.keep_alive_enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the keep-alive."""
        self.coordinator.async_set_keep_alive(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop the keep-alive."""
        self.coordinator.async_set_keep_alive(False)
