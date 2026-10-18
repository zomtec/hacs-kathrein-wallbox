"""Select platform for the Kathrein Wallbox EMS phase selection."""

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import KathreinControlEntity
from .model import EMS_RELAY_MATRIX_OPTIONS

PARALLEL_UPDATES = 1

RELAY_MATRIX_OPTION_BY_VALUE: dict[int, str] = {
    value: option for option, value in EMS_RELAY_MATRIX_OPTIONS.items()
}

RELAY_MATRIX_DESCRIPTION = SelectEntityDescription(
    key="ems_relay_matrix",
    translation_key="ems_relay_matrix",
    options=list(EMS_RELAY_MATRIX_OPTIONS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EMS phase selection."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([KathreinRelayMatrixSelect(coordinator)])


class KathreinRelayMatrixSelect(KathreinControlEntity, SelectEntity):
    """Choose between single-phase and three-phase EMS charging."""

    def __init__(self, coordinator: KathreinCoordinator) -> None:
        super().__init__(coordinator, RELAY_MATRIX_DESCRIPTION.key)
        self.entity_description = RELAY_MATRIX_DESCRIPTION

    @property
    def current_option(self) -> str | None:
        """Return the selected phases, or None for an unsupported register value."""
        value = self.coordinator.device.ems_control.relay_matrix
        if value is None:
            return None
        return RELAY_MATRIX_OPTION_BY_VALUE.get(value)

    async def async_select_option(self, option: str) -> None:
        """Enable EMS control and write the selected phases."""
        await self.coordinator.async_write_ems(
            "relay_matrix", EMS_RELAY_MATRIX_OPTIONS[option], enable_ems=True
        )
