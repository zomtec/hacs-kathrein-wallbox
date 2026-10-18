"""Sensor platform for Kathrein Wallbox."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import IntEnum

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import KathreinConfigEntry, KathreinCoordinator
from .entity import CoordinatorGetter, KathreinWallboxEntity
from .model import (
    COMPONENT_CHARGING_SESSION,
    COMPONENT_METER,
    COMPONENT_SESSION_ENERGY,
    MAINS_FREQUENCY_RANGE_HZ,
    MAINS_VOLTAGE_RANGE_V,
    ChargingState,
    CPState,
    PPState,
    RelayMatrix,
    finite,
    within,
)

PARALLEL_UPDATES = 0

# Session energy is read only while the meter answers.
METER_COMPONENTS = {COMPONENT_METER, COMPONENT_SESSION_ENERGY}

# PP value 0 is ambiguous; the device info cable bit picks one of these.
PP_CABLE_NOT_CONNECTED = "cable_not_connected"
PP_FIXED_CABLE_MOUNTED = "fixed_cable_mounted"

CHARGING_STATES: dict[ChargingState, str] = {
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
PP_STATES: dict[PPState, str] = {
    PPState.CABLE_NOT_CONNECTED_OR_FIXED: "not_connected_or_fixed_cable",
    PPState.AMP_13: "amp_13",
    PPState.AMP_20: "amp_20",
    PPState.AMP_32: "amp_32",
    PPState.AMP_63: "amp_63",
    PPState.ERROR: "error",
}
CP_STATES: dict[CPState, str] = {
    CPState.A: "state_a",
    CPState.B: "state_b",
    CPState.C: "state_c",
    CPState.D: "state_d",
    CPState.E: "state_e",
    CPState.F: "state_f",
}
RELAY_MATRIX_STATES: dict[RelayMatrix, str] = {
    RelayMatrix.PHASE_1: "phase_1",
    RelayMatrix.PHASE_2: "phase_2",
    RelayMatrix.PHASE_3: "phase_3",
    RelayMatrix.THREE_PHASES: "three_phases",
}


@dataclass(frozen=True, kw_only=True)
class KathreinSensorDescription(SensorEntityDescription):
    """Describe a Wallbox sensor and how to read its value."""

    value_fn: CoordinatorGetter[StateType]
    component: str | None = None


def _state[E: IntEnum](value: E | None, states: dict[E, str]) -> str | None:
    """Translate a decoded register value to its enum state key."""
    return None if value is None else states[value]


def _pp_state(coordinator: KathreinCoordinator) -> str | None:
    """Resolve the ambiguous PP value 0 using the fixed-cable bit."""
    value = coordinator.device.evse.pp_state
    if value != PPState.CABLE_NOT_CONNECTED_OR_FIXED:
        return _state(value, PP_STATES)
    cable_is_fixed = coordinator.device.identity.cable_is_fixed
    if cable_is_fixed is None:
        return PP_STATES[PPState.CABLE_NOT_CONNECTED_OR_FIXED]
    return PP_FIXED_CABLE_MOUNTED if cable_is_fixed else PP_CABLE_NOT_CONNECTED


SENSOR_DESCRIPTIONS: tuple[KathreinSensorDescription, ...] = (
    KathreinSensorDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: within(c.device.meter.voltage_l1, MAINS_VOLTAGE_RANGE_V),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: within(c.device.meter.voltage_l2, MAINS_VOLTAGE_RANGE_V),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: within(c.device.meter.voltage_l3, MAINS_VOLTAGE_RANGE_V),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="current_l1",
        translation_key="current_l1",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: finite(c.device.meter.current_l1),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="current_l2",
        translation_key="current_l2",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: finite(c.device.meter.current_l2),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="current_l3",
        translation_key="current_l3",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: finite(c.device.meter.current_l3),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="active_power_l1",
        translation_key="active_power_l1",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: finite(c.device.meter.active_power_l1),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="active_power_l2",
        translation_key="active_power_l2",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: finite(c.device.meter.active_power_l2),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="active_power_l3",
        translation_key="active_power_l3",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: finite(c.device.meter.active_power_l3),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="total_active_power",
        translation_key="total_active_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: finite(c.device.meter.total_active_power),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="total_energy",
        translation_key="total_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: finite(c.device.meter.total_energy),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="frequency",
        translation_key="frequency",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: within(c.device.meter.frequency, MAINS_FREQUENCY_RANGE_HZ),
        component=COMPONENT_METER,
    ),
    KathreinSensorDescription(
        key="charging_state",
        translation_key="charging_state",
        device_class=SensorDeviceClass.ENUM,
        options=[*CHARGING_STATES.values()],
        value_fn=lambda c: _state(c.device.evse.charging_state, CHARGING_STATES),
    ),
    KathreinSensorDescription(
        key="pp_state",
        translation_key="pp_state",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.ENUM,
        options=[
            *PP_STATES.values(),
            PP_CABLE_NOT_CONNECTED,
            PP_FIXED_CABLE_MOUNTED,
        ],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_pp_state,
    ),
    KathreinSensorDescription(
        key="cp_state",
        translation_key="cp_state",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.ENUM,
        options=[*CP_STATES.values()],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _state(c.device.evse.cp_state, CP_STATES),
    ),
    KathreinSensorDescription(
        key="granted_current",
        translation_key="granted_current",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.device.evse.granted_current,
    ),
    KathreinSensorDescription(
        key="granted_power",
        translation_key="granted_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.device.evse.granted_power,
    ),
    KathreinSensorDescription(
        key="charging_duration",
        translation_key="charging_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda c: c.device.evse.charging_duration,
    ),
    KathreinSensorDescription(
        key="charging_energy",
        translation_key="charging_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
        value_fn=lambda c: c.device.session_energy.charging_energy,
        component=COMPONENT_SESSION_ENERGY,
    ),
    KathreinSensorDescription(
        key="charging_tag",
        translation_key="charging_tag",
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.device.charging_session.charging_tag,
        component=COMPONENT_CHARGING_SESSION,
    ),
    KathreinSensorDescription(
        key="charging_session_id",
        translation_key="charging_session_id",
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.device.charging_session.charging_session_id,
        component=COMPONENT_CHARGING_SESSION,
    ),
    KathreinSensorDescription(
        key="timeout_period",
        translation_key="timeout_period",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.device.ems_control.timeout_period,
    ),
    KathreinSensorDescription(
        key="timeout_fallback_relay_matrix",
        translation_key="timeout_fallback_relay_matrix",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.ENUM,
        options=[*RELAY_MATRIX_STATES.values()],
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _state(
            c.device.ems_control.timeout_fallback_relay_matrix, RELAY_MATRIX_STATES
        ),
    ),
    KathreinSensorDescription(
        key="timeout_fallback_current",
        translation_key="timeout_fallback_current",
        entity_registry_enabled_default=False,
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.device.ems_control.timeout_fallback_current,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: KathreinConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Wallbox sensors."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        KathreinSensor(coordinator, description)
        for description in SENSOR_DESCRIPTIONS
        if coordinator.meter_detected or description.component not in METER_COMPONENTS
    )


class KathreinSensor(KathreinWallboxEntity, SensorEntity):
    """A sensor backed by a typed Wallbox register."""

    entity_description: KathreinSensorDescription

    def __init__(
        self,
        coordinator: KathreinCoordinator,
        description: KathreinSensorDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.component)
        self.entity_description = description

    @property
    def native_value(self) -> StateType | date | datetime | Decimal:
        """Return the decoded register value or the enum state key."""
        return self.entity_description.value_fn(self.coordinator)
