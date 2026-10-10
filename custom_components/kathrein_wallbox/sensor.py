"""Sensor platform for Kathrein Wallbox."""

import math
from dataclasses import dataclass

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_UNKNOWN,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import CoordinatorGetter, KathreinWallboxEntity, always_available
from .model import (
    MAINS_FREQUENCY_RANGE_HZ,
    MAINS_VOLTAGE_RANGE_V,
    MILLIAMPERE_PER_AMPERE,
    ChargingState,
    CPState,
    PPState,
    RelayMatrix,
)

# PP value 0 is ambiguous; the device info cable bit picks one of these.
PP_CABLE_NOT_CONNECTED = "cable_not_connected"
PP_FIXED_CABLE_MOUNTED = "fixed_cable_mounted"

CHARGING_STATES: dict[int, str] = {
    ChargingState.IDLE: "idle",
    ChargingState.EV_CONNECTED: "ev_connected",
    ChargingState.AUTHENTICATION_WAITING: "authentication_waiting",
    ChargingState.AUTHENTICATION_CONFIRMED: "authentication_confirmed",
    ChargingState.CHARGING_ACTIVE: "charging_active",
    ChargingState.CHARGING_PAUSED: "charging_paused",
    ChargingState.CHARGING_COMPLETED: "charging_completed",
    ChargingState.RFID_PAIRING: "rfid_pairing",
    ChargingState.ERROR: "error",
}
PP_STATES: dict[int, str] = {
    PPState.CABLE_NOT_CONNECTED_OR_FIXED: "not_connected_or_fixed_cable",
    PPState.AMP_13: "amp_13",
    PPState.AMP_20: "amp_20",
    PPState.AMP_32: "amp_32",
    PPState.AMP_63: "amp_63",
    PPState.ERROR: "error",
}
CP_STATES: dict[int, str] = {
    CPState.A: "state_a",
    CPState.B: "state_b",
    CPState.C: "state_c",
    CPState.D: "state_d",
    CPState.E: "state_e",
    CPState.F: "state_f",
}
RELAY_MATRIX_STATES: dict[int, str] = {
    RelayMatrix.PHASE_1: "phase_1",
    RelayMatrix.PHASE_2: "phase_2",
    RelayMatrix.PHASE_3: "phase_3",
    RelayMatrix.THREE_PHASES: "three_phases",
}


@dataclass(frozen=True, kw_only=True)
class KathreinSensorDescription(SensorEntityDescription):
    """Describe a Wallbox sensor and how to read its value."""

    value_fn: CoordinatorGetter[StateType]
    available_fn: CoordinatorGetter[bool] = always_available


def _finite(value: float | None) -> float | None:
    """Drop NaN and infinite readings."""
    if value is None or not math.isfinite(value):
        return None
    return value


def _within(value: float | None, bounds: tuple[int, int]) -> float | None:
    """Drop readings that are not finite or outside the inclusive bounds."""
    value = _finite(value)
    if value is None or not bounds[0] <= value <= bounds[1]:
        return None
    return value


def _amperes(milliamperes: int | None) -> float | None:
    """Convert a mA register value to A."""
    if milliamperes is None:
        return None
    return milliamperes / MILLIAMPERE_PER_AMPERE


def _state(value: int | None, states: dict[int, str]) -> str | None:
    """Translate a register value to its enum state key."""
    if value is None:
        return None
    return states.get(value, STATE_UNKNOWN)


def _pp_state(coordinator: KathreinCoordinator) -> str | None:
    """Resolve the ambiguous PP value 0 using the fixed-cable bit."""
    value = coordinator.evse.pp_state
    if value != PPState.CABLE_NOT_CONNECTED_OR_FIXED:
        return _state(value, PP_STATES)
    cable_is_fixed = coordinator.identity.cable_is_fixed
    if cable_is_fixed is None:
        return PP_STATES[PPState.CABLE_NOT_CONNECTED_OR_FIXED]
    return PP_FIXED_CABLE_MOUNTED if cable_is_fixed else PP_CABLE_NOT_CONNECTED


def _meter_available(coordinator: KathreinCoordinator) -> bool:
    """Return whether a plausible energy meter was detected."""
    return coordinator.meter_available


def _session_energy_available(coordinator: KathreinCoordinator) -> bool:
    """Return whether the session energy register is readable."""
    return coordinator.session_energy_available


SENSOR_DESCRIPTIONS: tuple[KathreinSensorDescription, ...] = (
    KathreinSensorDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _within(c.meter.voltage_l1, MAINS_VOLTAGE_RANGE_V),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _within(c.meter.voltage_l2, MAINS_VOLTAGE_RANGE_V),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _within(c.meter.voltage_l3, MAINS_VOLTAGE_RANGE_V),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="current_l1",
        translation_key="current_l1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _finite(c.meter.current_l1),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="current_l2",
        translation_key="current_l2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _finite(c.meter.current_l2),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="current_l3",
        translation_key="current_l3",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _finite(c.meter.current_l3),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="active_power_l1",
        translation_key="active_power_l1",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _finite(c.meter.active_power_l1),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="active_power_l2",
        translation_key="active_power_l2",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _finite(c.meter.active_power_l2),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="active_power_l3",
        translation_key="active_power_l3",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _finite(c.meter.active_power_l3),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="total_active_power",
        translation_key="total_active_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _finite(c.meter.total_active_power),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="total_energy",
        translation_key="total_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: _finite(c.meter.total_energy),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="frequency",
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _within(c.meter.frequency, MAINS_FREQUENCY_RANGE_HZ),
        available_fn=_meter_available,
    ),
    KathreinSensorDescription(
        key="charging_state",
        translation_key="charging_state",
        device_class=SensorDeviceClass.ENUM,
        options=[*CHARGING_STATES.values(), STATE_UNKNOWN],
        value_fn=lambda c: _state(c.evse.charging_state, CHARGING_STATES),
    ),
    KathreinSensorDescription(
        key="pp_state",
        translation_key="pp_state",
        device_class=SensorDeviceClass.ENUM,
        options=[
            *PP_STATES.values(),
            PP_CABLE_NOT_CONNECTED,
            PP_FIXED_CABLE_MOUNTED,
            STATE_UNKNOWN,
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_pp_state,
    ),
    KathreinSensorDescription(
        key="cp_state",
        translation_key="cp_state",
        device_class=SensorDeviceClass.ENUM,
        options=[*CP_STATES.values(), STATE_UNKNOWN],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _state(c.evse.cp_state, CP_STATES),
    ),
    KathreinSensorDescription(
        key="granted_current",
        translation_key="granted_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _amperes(c.evse.granted_current),
    ),
    KathreinSensorDescription(
        key="granted_power",
        translation_key="granted_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.evse.granted_power,
    ),
    KathreinSensorDescription(
        key="charging_duration",
        translation_key="charging_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.evse.charging_duration,
    ),
    KathreinSensorDescription(
        key="charging_energy",
        translation_key="charging_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.session_energy.charging_energy,
        available_fn=_session_energy_available,
    ),
    KathreinSensorDescription(
        key="relay_matrix",
        translation_key="relay_matrix",
        device_class=SensorDeviceClass.ENUM,
        options=[*RELAY_MATRIX_STATES.values(), STATE_UNKNOWN],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _state(c.ems_control.relay_matrix, RELAY_MATRIX_STATES),
    ),
    KathreinSensorDescription(
        key="charging_current",
        translation_key="charging_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _amperes(c.ems_control.charging_current),
    ),
    KathreinSensorDescription(
        key="timeout_period",
        translation_key="timeout_period",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.ems_control.timeout_period,
    ),
    KathreinSensorDescription(
        key="timeout_fallback_relay_matrix",
        translation_key="timeout_fallback_relay_matrix",
        device_class=SensorDeviceClass.ENUM,
        options=[*RELAY_MATRIX_STATES.values(), STATE_UNKNOWN],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _state(
            c.ems_control.timeout_fallback_relay_matrix, RELAY_MATRIX_STATES
        ),
    ),
    KathreinSensorDescription(
        key="timeout_fallback_current",
        translation_key="timeout_fallback_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _amperes(c.ems_control.timeout_fallback_current),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Wallbox sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        (
            KathreinRestoredSensor
            if description.state_class
            in (SensorStateClass.TOTAL, SensorStateClass.TOTAL_INCREASING)
            else KathreinSensor
        )(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
    )


class KathreinSensorBase(KathreinWallboxEntity):
    """Common description handling for Wallbox sensors."""

    entity_description: KathreinSensorDescription

    def __init__(
        self,
        coordinator: KathreinCoordinator,
        description: KathreinSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Hide sensors whose optional register block is absent or invalid."""
        return super().available and self.entity_description.available_fn(
            self.coordinator
        )

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Disable sensors of an optional register block until it is detected."""
        return super().entity_registry_enabled_default and (
            self.entity_description.available_fn(self.coordinator)
        )

    @property
    def native_value(self) -> StateType:
        """Return the decoded register value or the enum state key."""
        return self.entity_description.value_fn(self.coordinator)


class KathreinSensor(KathreinSensorBase, SensorEntity):
    """A sensor backed by a typed Wallbox register."""


class KathreinRestoredSensor(KathreinSensorBase, RestoreSensor):
    """Keep total energy available across communication gaps and restarts."""

    @property
    def available(self) -> bool:
        """Keep long-term energy statistics available across communication gaps."""
        return self.entity_description.available_fn(self.coordinator)

    async def async_added_to_hass(self) -> None:
        """Restore the previous value and process the current device reading."""
        await super().async_added_to_hass()
        if (last_data := await self.async_get_last_sensor_data()) is not None:
            self._attr_native_value = last_data.native_value
        self._process_value()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Keep the last good value when a register is temporarily unavailable."""
        self._process_value()
        super()._handle_coordinator_update()

    def _process_value(self) -> None:
        """Update the restored value only when the register is valid."""
        if (value := self.entity_description.value_fn(self.coordinator)) is not None:
            self._attr_native_value = value

    @property
    def native_value(self) -> StateType:
        """Return live energy or the last restored/valid reading."""
        value = self.entity_description.value_fn(self.coordinator)
        return value if value is not None else self._attr_native_value
