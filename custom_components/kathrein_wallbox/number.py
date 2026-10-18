"""Number platform for the Kathrein Wallbox EMS charging current."""

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import Platform, UnitOfElectricCurrent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import KathreinWallboxEntity, async_setup_control_entity
from .model import (
    EMS_CHARGING_PAUSED_A,
    EMS_MAX_CHARGING_CURRENT_A,
    EMS_MIN_CHARGING_CURRENT_A,
    MAX_CURRENT_11_KW_A,
)

PARALLEL_UPDATES = 1

CHARGING_CURRENT_DESCRIPTION = NumberEntityDescription(
    key="ems_charging_current",
    translation_key="ems_charging_current",
    device_class=NumberDeviceClass.CURRENT,
    native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    native_min_value=EMS_CHARGING_PAUSED_A,
    native_max_value=EMS_MAX_CHARGING_CURRENT_A,
    native_step=1,
    mode=NumberMode.BOX,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the EMS charging current control."""
    coordinator = entry.runtime_data.coordinator
    async_setup_control_entity(
        hass,
        coordinator,
        async_add_entities,
        Platform.NUMBER,
        CHARGING_CURRENT_DESCRIPTION.key,
        KathreinChargingCurrentNumber,
    )


class KathreinChargingCurrentNumber(KathreinWallboxEntity, NumberEntity):
    """Set the EMS charging current in whole amperes; 0 A pauses charging."""

    def __init__(self, coordinator: KathreinCoordinator) -> None:
        super().__init__(coordinator, CHARGING_CURRENT_DESCRIPTION.key)
        self.entity_description = CHARGING_CURRENT_DESCRIPTION

    @property
    def native_max_value(self) -> float:
        """Limit the setpoint to the power class of the Wallbox."""
        if self.coordinator.device.identity.is_11_kw:
            return MAX_CURRENT_11_KW_A
        return super().native_max_value

    @property
    def native_value(self) -> float | None:
        """Return the current setpoint, or None for a cancel or unknown value."""
        current = self.coordinator.device.ems_control.charging_current
        if current is None or not _is_valid_setpoint(current):
            return None
        return current

    async def async_set_native_value(self, value: float) -> None:
        """Enable EMS control and write the setpoint; below 6 A pauses charging."""
        current = round(value)
        # The Wallbox cannot charge below 6 A, so 1 to 5 A means no charging.
        if current < EMS_MIN_CHARGING_CURRENT_A:
            current = EMS_CHARGING_PAUSED_A
        await self.coordinator.async_write_ems(
            "charging_current", current, enable_ems=True
        )


def _is_valid_setpoint(current: float) -> bool:
    """Return whether the register accepts the setpoint (0 or 6 ... 32 A)."""
    return (
        current == EMS_CHARGING_PAUSED_A
        or EMS_MIN_CHARGING_CURRENT_A <= current <= EMS_MAX_CHARGING_CURRENT_A
    )
