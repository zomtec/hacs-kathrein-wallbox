"""Number platform for the Kathrein Wallbox EMS charging current."""

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import KathreinWallboxEntity
from .model import (
    EMS_MAX_CHARGING_CURRENT_MA,
    EMS_MIN_CHARGING_CURRENT_MA,
    MAX_CURRENT_11_KW_MA,
    MILLIAMPERE_PER_AMPERE,
)

PARALLEL_UPDATES = 1

CHARGING_CURRENT_DESCRIPTION = NumberEntityDescription(
    key="ems_charging_current",
    translation_key="ems_charging_current",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_min_value=EMS_MIN_CHARGING_CURRENT_MA // MILLIAMPERE_PER_AMPERE,
    native_max_value=EMS_MAX_CHARGING_CURRENT_MA // MILLIAMPERE_PER_AMPERE,
    native_step=1,
    mode=NumberMode.SLIDER,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EMS charging current control."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities([KathreinChargingCurrentNumber(coordinator)])


class KathreinChargingCurrentNumber(KathreinWallboxEntity, NumberEntity):
    """Set the EMS charging current in whole amperes."""

    def __init__(self, coordinator: KathreinCoordinator) -> None:
        super().__init__(coordinator, CHARGING_CURRENT_DESCRIPTION.key)
        self.entity_description = CHARGING_CURRENT_DESCRIPTION

    @property
    def native_max_value(self) -> float:
        """Limit the setpoint to the power class of the Wallbox."""
        if self.coordinator.identity.is_11_kw:
            return MAX_CURRENT_11_KW_MA // MILLIAMPERE_PER_AMPERE
        return super().native_max_value

    @property
    def native_value(self) -> float | None:
        """Return the current setpoint, or None while charging is paused or cancelled."""
        current_ma = self.coordinator.ems_control.charging_current
        if (
            current_ma is None
            or not EMS_MIN_CHARGING_CURRENT_MA
            <= current_ma
            <= EMS_MAX_CHARGING_CURRENT_MA
        ):
            return None
        return current_ma / MILLIAMPERE_PER_AMPERE

    async def async_set_native_value(self, value: float) -> None:
        """Write the new setpoint to the EMS charging current register."""
        await self.coordinator.async_write_ems(
            "charging_current", round(value) * MILLIAMPERE_PER_AMPERE
        )
