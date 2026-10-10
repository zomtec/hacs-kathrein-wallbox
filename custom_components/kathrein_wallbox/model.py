"""Typed register models for the Kathrein Wallbox."""

import math
from enum import IntEnum, IntFlag

from modbus_connection.model import Component, float32, integer, string, uint32

# Readings outside these ranges are rejected as implausible.
MAINS_VOLTAGE_RANGE_V = (80, 300)
MAINS_FREQUENCY_RANGE_HZ = (45, 65)

# Currents are reported and written in mA.
MILLIAMPERE_PER_AMPERE = 1000
MAX_CURRENT_11_KW_MA = 16000
# EMS setpoints offered by the services; 0 pauses charging or disables the timeout.
EMS_CHARGING_CURRENTS_MA = (0, 6000, 8000, 10000, 12000, 16000, 20000, 24000, 32000)
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


class WallboxIdentity(Component):
    """The compact identity range read during config flow validation."""

    mapping_version = integer(MAPPING_VERSION_ADDRESS, signed=False)
    device_number = string(DEVICE_NUMBER_ADDRESS, IDENTITY_STRING_REGISTER_COUNT)
    device_type = string(DEVICE_TYPE_ADDRESS, IDENTITY_STRING_REGISTER_COUNT)
    serial = string(SERIAL_ADDRESS, SERIAL_REGISTER_COUNT)
    device_info = integer(DEVICE_INFO_ADDRESS, signed=False)

    @property
    def is_11_kw(self) -> bool:
        """Return whether the device info register identifies an 11 kW model."""
        return (
            self.device_info is not None
            and self.device_info & DEVICE_INFO_POWER_CLASS_MASK
            == DEVICE_INFO_POWER_CLASS_11_KW
        )

    @property
    def cable_is_fixed(self) -> bool | None:
        """Return whether the device info register identifies a fixed cable."""
        if self.device_info is None:
            return None
        return not bool(self.device_info & DEVICE_INFO_DETACHABLE_CABLE)


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
        voltage_low, voltage_high = MAINS_VOLTAGE_RANGE_V
        voltages = (self.voltage_l1, self.voltage_l2, self.voltage_l3)
        if any(
            value is not None
            and math.isfinite(value)
            and voltage_low <= value <= voltage_high
            for value in voltages
        ):
            return True
        frequency_low, frequency_high = MAINS_FREQUENCY_RANGE_HZ
        frequency = self.frequency
        return frequency is not None and frequency_low <= frequency <= frequency_high


class WallboxSessionEnergy(Component):
    """Meter-derived energy counter for the current or last charging session."""

    charging_energy = uint32(CHARGING_ENERGY_ADDRESS, unit="Wh")


class WallboxEVSE(Component):
    """Charging and EVSE registers, independent of the optional meter."""

    charging_state = integer(CHARGING_STATE_ADDRESS, signed=False)
    error_states = integer(ERROR_STATES_ADDRESS, signed=False)
    pp_state = integer(PP_STATE_ADDRESS, signed=False)
    cp_state = integer(CP_STATE_ADDRESS, signed=False)
    relay_state = integer(RELAY_STATE_ADDRESS, signed=False)
    granted_current = integer(GRANTED_CURRENT_ADDRESS, signed=False, unit="mA")
    granted_power = integer(GRANTED_POWER_ADDRESS, signed=False, unit="W")
    charging_duration = uint32(CHARGING_DURATION_ADDRESS, unit="s")


class WallboxEMSControl(Component):
    """EMS control registers for remote charge control."""

    control_register = integer(
        EMS_CONTROL_REGISTER_ADDRESS, signed=False, writable=True
    )
    relay_matrix = integer(EMS_RELAY_MATRIX_ADDRESS, signed=False, writable=True)
    charging_current = integer(
        EMS_CHARGING_CURRENT_ADDRESS, signed=False, writable=True, unit="mA"
    )
    timeout_period = integer(
        EMS_TIMEOUT_PERIOD_ADDRESS, signed=False, writable=True, unit="s"
    )
    timeout_fallback_relay_matrix = integer(
        EMS_TIMEOUT_FALLBACK_RELAY_MATRIX_ADDRESS, signed=False, writable=True
    )
    timeout_fallback_current = integer(
        EMS_TIMEOUT_FALLBACK_CURRENT_ADDRESS, signed=False, writable=True, unit="mA"
    )
