"""Typed, read-only register models for the Kathrein Wallbox."""

import math
from enum import IntEnum

from modbus_connection.model import Component, float32, integer, string, uint32

METER_FIELDS = frozenset(
    {
        "voltage_l1",
        "voltage_l2",
        "voltage_l3",
        "current_l1",
        "current_l2",
        "current_l3",
        "active_power_l1",
        "active_power_l2",
        "active_power_l3",
        "total_active_power",
        "total_energy",
        "frequency",
        "charging_energy",
    }
)


class ChargingState(IntEnum):
    """EVSE charging state values."""

    IDLE = 0
    EV_CONNECTED = 1
    AUTHENTICATION_WAITING = 2
    AUTHENTICATION_CONFIRMED = 3
    CHARGING_ACTIVE = 4
    CHARGING_PAUSED = 5
    CHARGING_COMPLETED = 6
    RFID_PAIRING = 7
    ERROR = 0xFFFF


class PPState(IntEnum):
    """Proximity pilot values."""

    CABLE_NOT_CONNECTED_OR_FIXED = 0
    AMP_13 = 13
    AMP_20 = 20
    AMP_32 = 32
    AMP_63 = 63
    ERROR = 0xFFFF


class CPState(IntEnum):
    """Control pilot values."""

    A = 0
    B = 1
    C = 2
    D = 3
    E = 4
    F = 5


class WallboxIdentity(Component):
    """The compact identity range read during config flow validation."""

    mapping_version = integer(0x0000, signed=False)
    device_number = string(0x0001, 8)
    device_type = string(0x0009, 8)
    serial = string(0x0011, 8)
    device_info = integer(0x0019, signed=False)

    @property
    def is_11_kw(self) -> bool:
        """Return whether the device info register identifies an 11 kW model."""
        return self.device_info is not None and self.device_info & 0x0003 == 0x0001

    @property
    def cable_is_fixed(self) -> bool | None:
        """Return whether the device info register identifies a fixed cable."""
        if self.device_info is None:
            return None
        return not bool(self.device_info & 0x0010)


class WallboxMeter(Component):
    """Optional energy-meter registers."""

    voltage_l1 = float32(0x0030, unit="V")
    voltage_l2 = float32(0x0032, unit="V")
    voltage_l3 = float32(0x0034, unit="V")
    current_l1 = float32(0x0036, unit="A")
    current_l2 = float32(0x0038, unit="A")
    current_l3 = float32(0x003A, unit="A")
    active_power_l1 = float32(0x003C, unit="W")
    active_power_l2 = float32(0x003E, unit="W")
    active_power_l3 = float32(0x0040, unit="W")

    total_active_power = float32(0x0054, unit="W")
    total_energy = float32(0x005C, unit="Wh")
    frequency = float32(0x005E, unit="Hz")

    @property
    def has_plausible_reference(self) -> bool:
        """Require at least one plausible mains voltage or frequency reading."""
        voltages = (self.voltage_l1, self.voltage_l2, self.voltage_l3)
        if any(
            value is not None and math.isfinite(value) and 80 <= value <= 300
            for value in voltages
        ):
            return True
        frequency = self.frequency
        return frequency is not None and 45 <= frequency <= 65


class WallboxSessionEnergy(Component):
    """Meter-derived energy counter for the current or last charging session."""

    charging_energy = uint32(0x0069, unit="Wh")


class WallboxEVSE(Component):
    """Charging and EVSE registers, independent of the optional meter."""

    charging_state = integer(0x0060, signed=False)
    error_states = integer(0x0061, signed=False)
    pp_state = integer(0x0062, signed=False)
    cp_state = integer(0x0063, signed=False)
    relay_state = integer(0x0064, signed=False)
    granted_current = integer(0x0065, signed=False)
    granted_power = integer(0x0066, signed=False)
    charging_duration = uint32(0x0067)


class WallboxEMSControl(Component):
    """EMS control registers for remote charge control."""

    control_register = integer(0x00A0, signed=False)
    relay_matrix = integer(0x00A1, signed=False)
    charging_current = integer(0x00A2, signed=False)
    timeout_period = integer(0x00A3, signed=False)
    timeout_fallback_relay_matrix = integer(0x00A4, signed=False)
    timeout_fallback_current = integer(0x00A5, signed=False)