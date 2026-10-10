"""Sensor platform for Kathrein Wallbox."""

from __future__ import annotations

import math

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
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

from .coordinator import KathreinCoordinator, WallboxRuntimeData
from .entity import KathreinWallboxEntity
from .model import METER_FIELDS, ChargingState, CPState, PPState

_ENUM_UNKNOWN = "unknown"

CHARGING_STATES = {
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
PP_STATES = {
    PPState.CABLE_NOT_CONNECTED_OR_FIXED: "not_connected_or_fixed_cable",
    PPState.AMP_13: "amp_13",
    PPState.AMP_20: "amp_20",
    PPState.AMP_32: "amp_32",
    PPState.AMP_63: "amp_63",
    PPState.ERROR: "error",
}
CP_STATES = {
    CPState.A: "state_a",
    CPState.B: "state_b",
    CPState.C: "state_c",
    CPState.D: "state_d",
    CPState.E: "state_e",
    CPState.F: "state_f",
}
RELAY_MATRIX_STATES = {
    1: "line_1",
    2: "line_2",
    4: "line_3",
    7: "three_lines",
}

ENUM_OPTIONS = {
    "charging_state": [*CHARGING_STATES.values(), _ENUM_UNKNOWN],
    "pp_state": [
        *PP_STATES.values(),
        "cable_not_connected",
        "fixed_cable_mounted",
        _ENUM_UNKNOWN,
    ],
    "cp_state": [*CP_STATES.values(), _ENUM_UNKNOWN],
    "relay_matrix": [*RELAY_MATRIX_STATES.values(), _ENUM_UNKNOWN],
    "timeout_fallback_relay_matrix": [*RELAY_MATRIX_STATES.values(), _ENUM_UNKNOWN],
}
ENUM_MAPPINGS: dict[str, dict[int, str]] = {
    "charging_state": {int(key): value for key, value in CHARGING_STATES.items()},
    "pp_state": {int(key): value for key, value in PP_STATES.items()},
    "cp_state": {int(key): value for key, value in CP_STATES.items()},
    "relay_matrix": RELAY_MATRIX_STATES,
    "timeout_fallback_relay_matrix": RELAY_MATRIX_STATES,
}

EMS_CONTROL_SENSOR_KEYS = {
    "relay_matrix",
    "charging_current",
    "timeout_period",
    "timeout_fallback_relay_matrix",
    "timeout_fallback_current",
}

SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="voltage_l1",
        translation_key="voltage_l1",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="voltage_l2",
        translation_key="voltage_l2",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="voltage_l3",
        translation_key="voltage_l3",
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="current_l1",
        translation_key="current_l1",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="current_l2",
        translation_key="current_l2",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="current_l3",
        translation_key="current_l3",
        device_class=SensorDeviceClass.CURRENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="active_power_l1",
        translation_key="active_power_l1",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="active_power_l2",
        translation_key="active_power_l2",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="active_power_l3",
        translation_key="active_power_l3",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="total_active_power",
        translation_key="total_active_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="total_energy",
        translation_key="total_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="frequency",
        translation_key="frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    SensorEntityDescription(
        key="charging_state",
        translation_key="charging_state",
        device_class=SensorDeviceClass.ENUM,
        options=ENUM_OPTIONS["charging_state"],
    ),
    SensorEntityDescription(
        key="pp_state",
        translation_key="pp_state",
        device_class=SensorDeviceClass.ENUM,
        options=ENUM_OPTIONS["pp_state"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="cp_state",
        translation_key="cp_state",
        device_class=SensorDeviceClass.ENUM,
        options=ENUM_OPTIONS["cp_state"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="granted_current",
        translation_key="granted_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="granted_power",
        translation_key="granted_power",
        device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="charging_duration",
        translation_key="charging_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
    ),
    SensorEntityDescription(
        key="charging_energy",
        translation_key="charging_energy",
        device_class=SensorDeviceClass.ENERGY,
        native_unit_of_measurement=UnitOfEnergy.WATT_HOUR,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    SensorEntityDescription(
        key="relay_matrix",
        translation_key="relay_matrix",
        device_class=SensorDeviceClass.ENUM,
        options=ENUM_OPTIONS["relay_matrix"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="charging_current",
        translation_key="charging_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="timeout_period",
        translation_key="timeout_period",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="timeout_fallback_relay_matrix",
        translation_key="timeout_fallback_relay_matrix",
        device_class=SensorDeviceClass.ENUM,
        options=ENUM_OPTIONS["timeout_fallback_relay_matrix"],
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    SensorEntityDescription(
        key="timeout_fallback_current",
        translation_key="timeout_fallback_current",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[WallboxRuntimeData],
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
    """Common value handling for typed Wallbox sensors."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: KathreinCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Hide meter entities when the optional meter is absent or invalid."""
        if self.entity_description.key == "charging_energy":
            return super().available and self.coordinator.session_energy_available
        return super().available and (
            self.entity_description.key not in METER_FIELDS
            or self.coordinator.meter_available
        )

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Disable meter-derived entities by default when no meter is detected."""
        if self.entity_description.key == "charging_energy":
            return self.coordinator.session_energy_available
        if self.entity_description.key in METER_FIELDS:
            return self.coordinator.meter_available
        return super().entity_registry_enabled_default

    @property
    def native_value(self) -> str | float | int | None:
        """Return a finite register value or the translated enum state."""
        return self._get_native_value()

    def _get_native_value(self) -> str | float | int | None:
        """Read and normalize the current register value."""
        key = self.entity_description.key
        if key == "charging_energy":
            component = self.coordinator.session_energy
        elif key in METER_FIELDS:
            component = self.coordinator.meter
        elif key in EMS_CONTROL_SENSOR_KEYS:
            component = self.coordinator.ems_control
        else:
            component = self.coordinator.evse
        value = getattr(component, key)
        if value is None:
            return None
        enum_mapping = ENUM_MAPPINGS.get(self.entity_description.key)
        if enum_mapping is not None:
            if key == "pp_state" and int(value) == int(
                PPState.CABLE_NOT_CONNECTED_OR_FIXED
            ):
                cable_is_fixed = self.coordinator.identity.cable_is_fixed
                if cable_is_fixed is None:
                    return "not_connected_or_fixed_cable"
                return (
                    "fixed_cable_mounted" if cable_is_fixed else "cable_not_connected"
                )
            return enum_mapping.get(int(value), _ENUM_UNKNOWN)
        if self.entity_description.key in {
            "granted_current",
            "charging_current",
            "timeout_fallback_current",
        }:
            return value / 1000
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if key.startswith("voltage_") and not 80 <= value <= 300:
            return None
        if key == "frequency" and not 45 <= value <= 65:
            return None
        return value


class KathreinSensor(KathreinSensorBase, SensorEntity):
    """A sensor backed by a typed Wallbox register."""


class KathreinRestoredSensor(KathreinSensorBase, RestoreSensor):
    """Keep total energy available across communication gaps and restarts."""

    @property
    def available(self) -> bool:
        """Keep long-term energy statistics available across communication gaps."""
        if self.entity_description.key == "charging_energy":
            return self.coordinator.session_energy_available
        return self.coordinator.meter_available

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
        if (value := self._get_native_value()) is not None:
            self._attr_native_value = value

    @property
    def native_value(self) -> str | float | int | None:
        """Return live energy or the last restored/valid reading."""
        value = self._get_native_value()
        return value if value is not None else self._attr_native_value
