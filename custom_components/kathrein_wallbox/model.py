"""Typed register models for the Kathrein Wallbox."""

import math
from enum import IntEnum, IntFlag

from modbus_connection import ModbusUnit
from modbus_connection.model import (
    Component,
    Device,
    flags,
    float32,
    gauge,
    integer,
    string,
    uint32,
)

# Readings outside these ranges are rejected as implausible.
MAINS_VOLTAGE_RANGE_V = (80, 300)
MAINS_FREQUENCY_RANGE_HZ = (45, 65)

# Currents are reported and written in mA; their fields scale them to A.
AMPERES_PER_MILLIAMPERE = 0.001
MAX_CURRENT_11_KW_A = 16
# EMS current setpoints accept 0 A (pause) or 6 ... 32 A.
EMS_CHARGING_PAUSED_A = 0
EMS_MIN_CHARGING_CURRENT_A = 6
EMS_MAX_CHARGING_CURRENT_A = 32
# EMS timeout periods offered by the services; 0 disables the timeout.
EMS_TIMEOUT_PERIODS_S = (0, 30, 60, 120, 180, 300, 600)

# Bit 15 of the EMS control register switches EMS control on.
EMS_CONTROL_ENABLED = 0x8000
EMS_CONTROL_DISABLED = 0x0000

# Modbus holding register addresses (see modbus_register/Modbus-Server.md).
MAPPING_VERSION_ADDRESS = 0x0000
DEVICE_NUMBER_ADDRESS = 0x0001
DEVICE_TYPE_ADDRESS = 0x0009
SERIAL_ADDRESS = 0x0011
DEVICE_INFO_ADDRESS = 0x0019
LINE_MAPPING_ADDRESS = 0x001A
# Each identity string spans 8 registers (16 characters).
IDENTITY_STRING_REGISTER_COUNT = 8
SERIAL_REGISTER_COUNT = IDENTITY_STRING_REGISTER_COUNT

VOLTAGE_L1_ADDRESS = 0x0030
VOLTAGE_L2_ADDRESS = 0x0032
VOLTAGE_L3_ADDRESS = 0x0034
CURRENT_L1_ADDRESS = 0x0036
CURRENT_L2_ADDRESS = 0x0038
CURRENT_L3_ADDRESS = 0x003A
ACTIVE_POWER_L1_ADDRESS = 0x003C
ACTIVE_POWER_L2_ADDRESS = 0x003E
ACTIVE_POWER_L3_ADDRESS = 0x0040
TOTAL_ACTIVE_POWER_ADDRESS = 0x0054
TOTAL_ENERGY_ADDRESS = 0x005C
FREQUENCY_ADDRESS = 0x005E

CHARGING_STATE_ADDRESS = 0x0060
ERROR_STATES_ADDRESS = 0x0061
PP_STATE_ADDRESS = 0x0062
CP_STATE_ADDRESS = 0x0063
RELAY_STATE_ADDRESS = 0x0064
GRANTED_CURRENT_ADDRESS = 0x0065
GRANTED_POWER_ADDRESS = 0x0066
CHARGING_DURATION_ADDRESS = 0x0067
CHARGING_ENERGY_ADDRESS = 0x0069
CHARGING_TAG_INFO_ADDRESS = 0x0070
CHARGING_SESSION_ID_ADDRESS = 0x0088
# Tag info spans 24 registers (48 characters), the session GUID 18 (36 characters).
CHARGING_TAG_INFO_REGISTER_COUNT = 24
CHARGING_SESSION_ID_REGISTER_COUNT = 18

EMS_CONTROL_REGISTER_ADDRESS = 0x00A0
EMS_RELAY_MATRIX_ADDRESS = 0x00A1
EMS_CHARGING_CURRENT_ADDRESS = 0x00A2
EMS_TIMEOUT_PERIOD_ADDRESS = 0x00A3
EMS_TIMEOUT_FALLBACK_RELAY_MATRIX_ADDRESS = 0x00A4
EMS_TIMEOUT_FALLBACK_CURRENT_ADDRESS = 0x00A5

# Device info register: bits 0-1 hold the power class, bit 4 is set for a plug.
DEVICE_INFO_POWER_CLASS_MASK = 0x0003
DEVICE_INFO_POWER_CLASS_11_KW = 0x0001
DEVICE_INFO_DETACHABLE_CABLE = 0x0010


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


class RelayMatrix(IntEnum):
    """Phase selection bitmask of the EMS relay matrix."""

    PHASE_1 = 0x0001
    PHASE_2 = 0x0002
    PHASE_3 = 0x0004
    THREE_PHASES = 0x0007


class LineMapping(IntEnum):
    """Order in which the supply lines are wired to the Wallbox terminals."""

    L1_L2_L3 = 0
    L1_L3_L2 = 1
    L2_L3_L1 = 2
    L2_L1_L3 = 3
    L3_L1_L2 = 4
    L3_L2_L1 = 5


# The register manual marks these line mappings as invalid phase rotation.
INVALID_PHASE_ROTATIONS = frozenset(
    {LineMapping.L1_L3_L2, LineMapping.L2_L1_L3, LineMapping.L3_L2_L1}
)


class ErrorState(IntFlag):
    """Fault bits of the EVSE error register."""

    RELAY_WELDED = 0x0001
    RESIDUAL_DC_CURRENT = 0x0002
    SOCKET_LOCK_ERROR = 0x0004
    CHARGING_OVERCURRENT = 0x0008
    VENTILATION_UNAVAILABLE = 0x0010
    CP_SHORT_CIRCUIT = 0x0020
    CP_LOOP_BROKEN = 0x0040
    PP_SHORT_CIRCUIT = 0x0080
    INTERNAL_ERROR = 0x8000


class RelayState(IntFlag):
    """Phase relay bits of the EVSE relay state register."""

    RELAY_L1 = 0x0001
    RELAY_L2 = 0x0002
    RELAY_L3 = 0x0004


# Selectable relay matrix setpoints; the manual reserves phases 2 and 3 for future use.
EMS_RELAY_MATRIX_OPTIONS = {
    "phase_1": RelayMatrix.PHASE_1,
    "three_phases": RelayMatrix.THREE_PHASES,
}


class WallboxIdentity(Component):
    """The compact identity range read by the config flow and the coordinator."""

    mapping_version = integer(MAPPING_VERSION_ADDRESS, signed=False)
    device_number = string(DEVICE_NUMBER_ADDRESS, IDENTITY_STRING_REGISTER_COUNT)
    device_type = string(DEVICE_TYPE_ADDRESS, IDENTITY_STRING_REGISTER_COUNT)
    serial = string(SERIAL_ADDRESS, SERIAL_REGISTER_COUNT)
    device_info = integer(DEVICE_INFO_ADDRESS, signed=False)
    line_mapping = integer(LINE_MAPPING_ADDRESS, signed=False)

    @property
    def is_11_kw(self) -> bool:
        """Return whether the device info register identifies an 11 kW model."""
        return (
            self.device_info is not None
            and self.device_info & DEVICE_INFO_POWER_CLASS_MASK
            == DEVICE_INFO_POWER_CLASS_11_KW
        )

    @property
    def invalid_phase_rotation(self) -> LineMapping | None:
        """Return the line mapping if it is an invalid phase rotation."""
        line_mapping = self.line_mapping
        if line_mapping is None or line_mapping not in INVALID_PHASE_ROTATIONS:
            return None
        return LineMapping(line_mapping)

    @property
    def cable_is_fixed(self) -> bool | None:
        """Return whether the device info register identifies a fixed cable."""
        if self.device_info is None:
            return None
        return not bool(self.device_info & DEVICE_INFO_DETACHABLE_CABLE)


def finite(value: float | None) -> float | None:
    """Drop NaN and infinite readings."""
    if value is None or not math.isfinite(value):
        return None
    return value


def within(value: float | None, bounds: tuple[int, int]) -> float | None:
    """Drop readings that are not finite or outside the inclusive bounds."""
    value = finite(value)
    if value is None or not bounds[0] <= value <= bounds[1]:
        return None
    return value


class WallboxMeter(Component):
    """Optional energy-meter registers."""

    voltage_l1 = float32(VOLTAGE_L1_ADDRESS, unit="V")
    voltage_l2 = float32(VOLTAGE_L2_ADDRESS, unit="V")
    voltage_l3 = float32(VOLTAGE_L3_ADDRESS, unit="V")
    current_l1 = float32(CURRENT_L1_ADDRESS, unit="A")
    current_l2 = float32(CURRENT_L2_ADDRESS, unit="A")
    current_l3 = float32(CURRENT_L3_ADDRESS, unit="A")
    active_power_l1 = float32(ACTIVE_POWER_L1_ADDRESS, unit="W")
    active_power_l2 = float32(ACTIVE_POWER_L2_ADDRESS, unit="W")
    active_power_l3 = float32(ACTIVE_POWER_L3_ADDRESS, unit="W")

    total_active_power = float32(TOTAL_ACTIVE_POWER_ADDRESS, unit="W")
    total_energy = float32(TOTAL_ENERGY_ADDRESS, unit="Wh")
    frequency = float32(FREQUENCY_ADDRESS, unit="Hz")

    @property
    def has_plausible_reference(self) -> bool:
        """Require at least one plausible mains voltage or frequency reading."""
        voltages = (self.voltage_l1, self.voltage_l2, self.voltage_l3)
        return (
            any(within(value, MAINS_VOLTAGE_RANGE_V) is not None for value in voltages)
            or within(self.frequency, MAINS_FREQUENCY_RANGE_HZ) is not None
        )


class WallboxSessionEnergy(Component):
    """Meter-derived energy counter for the current or last charging session."""

    charging_energy = uint32(CHARGING_ENERGY_ADDRESS, unit="Wh")


class WallboxEVSE(Component):
    """Charging and EVSE registers, independent of the optional meter."""

    charging_state = integer(CHARGING_STATE_ADDRESS, signed=False)
    error_states = flags(ERROR_STATES_ADDRESS, ErrorState)
    pp_state = integer(PP_STATE_ADDRESS, signed=False)
    cp_state = integer(CP_STATE_ADDRESS, signed=False)
    relay_state = flags(RELAY_STATE_ADDRESS, RelayState)
    granted_current = gauge(
        GRANTED_CURRENT_ADDRESS, AMPERES_PER_MILLIAMPERE, signed=False, unit="A"
    )
    granted_power = integer(GRANTED_POWER_ADDRESS, signed=False, unit="W")
    charging_duration = uint32(CHARGING_DURATION_ADDRESS, unit="s")


class WallboxChargingSession(Component):
    """Tag and GUID of the current or last charging session."""

    tag_info = string(CHARGING_TAG_INFO_ADDRESS, CHARGING_TAG_INFO_REGISTER_COUNT)
    session_id = string(CHARGING_SESSION_ID_ADDRESS, CHARGING_SESSION_ID_REGISTER_COUNT)

    @property
    def charging_tag(self) -> str | None:
        """Return the authorizing tag, or "VOID" when charging needs no authentication."""
        # The tag string ends at its first 0x00 terminator.
        return (self.tag_info or "").partition("\x00")[0] or None

    @property
    def charging_session_id(self) -> str | None:
        """Return the GUID of the current or last charging session."""
        return self.session_id or None


class WallboxEMSControl(Component):
    """EMS control registers for remote charge control."""

    control_register = integer(
        EMS_CONTROL_REGISTER_ADDRESS, signed=False, writable=True
    )
    relay_matrix = integer(EMS_RELAY_MATRIX_ADDRESS, signed=False, writable=True)
    charging_current = gauge(
        EMS_CHARGING_CURRENT_ADDRESS,
        AMPERES_PER_MILLIAMPERE,
        signed=False,
        writable=True,
        unit="A",
    )
    timeout_period = integer(
        EMS_TIMEOUT_PERIOD_ADDRESS, signed=False, writable=True, unit="s"
    )
    timeout_fallback_relay_matrix = integer(
        EMS_TIMEOUT_FALLBACK_RELAY_MATRIX_ADDRESS, signed=False, writable=True
    )
    timeout_fallback_current = gauge(
        EMS_TIMEOUT_FALLBACK_CURRENT_ADDRESS,
        AMPERES_PER_MILLIAMPERE,
        signed=False,
        writable=True,
        unit="A",
    )

    @property
    def is_enabled(self) -> bool:
        """Return whether the control register has EMS control switched on."""
        return self.control_register is not None and bool(
            self.control_register & EMS_CONTROL_ENABLED
        )


# Component names are the WallboxDevice attributes the coordinator polls.
COMPONENT_EVSE = "evse"
COMPONENT_EMS_CONTROL = "ems_control"
COMPONENT_CHARGING_SESSION = "charging_session"
COMPONENT_METER = "meter"
COMPONENT_SESSION_ENERGY = "session_energy"


class WallboxDevice(Device):
    """The Wallbox components, with the static identity read once at setup."""

    def __init__(self, unit: ModbusUnit) -> None:
        super().__init__(unit)
        self.identity = WallboxIdentity(unit)
        self.evse = WallboxEVSE(unit)
        self.ems_control = WallboxEMSControl(unit)
        self.charging_session = WallboxChargingSession(unit)
        self.meter = WallboxMeter(unit)
        self.session_energy = WallboxSessionEnergy(unit)

    async def _async_setup(self) -> None:
        """Read the static device identity once before the first poll."""
        await self.identity.async_update()
