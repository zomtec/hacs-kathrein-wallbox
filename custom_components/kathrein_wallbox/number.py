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
    EMS_CHARGING_PAUSED_MA,
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
    native_min_value=EMS_CHARGING_PAUSED_MA // MILLIAMPERE_PER_AMPERE,
    native_max_value=EMS_MAX_CHARGING_CURRENT_MA // MILLIAMPERE_PER_AMPERE,
    native_step=1,
    mode=NumberMode.BOX,
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
    """Set the EMS charging current in whole amperes; 0 A pauses charging."""

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
        """Return the current setpoint, or None for a cancel or unknown value."""
        current_ma = self.coordinator.ems_control.charging_current
        if current_ma is None or not _is_valid_setpoint(current_ma):
            return None
        return current_ma / MILLIAMPERE_PER_AMPERE

    async def async_set_native_value(self, value: float) -> None:
        """Write the setpoint; values below the minimum current pause charging."""
        current_ma = round(value) * MILLIAMPERE_PER_AMPERE
        # The Wallbox cannot charge below 6 A, so 1 to 5 A means no charging.
        if current_ma < EMS_MIN_CHARGING_CURRENT_MA:
            current_ma = EMS_CHARGING_PAUSED_MA
        await self.coordinator.async_write_ems("charging_current", current_ma)


def _is_valid_setpoint(current_ma: int) -> bool:
    """Return whether the register accepts the setpoint (0 or 6000 ... 32000 mA)."""
    return (
        current_ma == EMS_CHARGING_PAUSED_MA
        or EMS_MIN_CHARGING_CURRENT_MA <= current_ma <= EMS_MAX_CHARGING_CURRENT_MA
    )
