"""Tests for the Kathrein Wallbox EMS services."""

from collections.abc import AsyncGenerator

import probatio
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from modbus_connection import ModbusError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox import (
    SERVICE_SET_CHARGING_CURRENT,
    SERVICE_SET_EMS_CONTROL_ENABLED,
    SERVICE_SET_RELAY_MATRIX,
    SERVICE_SET_TIMEOUT_FALLBACK_CURRENT,
    SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
    SERVICE_SET_TIMEOUT_PERIOD,
    async_setup,
)
from custom_components.kathrein_wallbox.const import CONF_ALLOW_CONTROL, DOMAIN
from custom_components.kathrein_wallbox.coordinator import (
    KathreinCoordinator,
    WallboxRuntimeData,
)

DEVICE_INFO_ADDRESS = 0x0019
DEVICE_INFO_11_KW = 0x0001
EMS_CONTROL_ADDRESS = 0x00A0


def _writes(unit) -> list[tuple[int, list[int]]]:
    return [(event.address, event.values) for event in unit.write_events]


def _async_add_device(hass, entry: MockConfigEntry) -> dr.DeviceEntry:
    """Register a device for the given config entry."""
    return dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(entry.domain, entry.entry_id)}
    )


def _device_id(hass, entry: MockConfigEntry) -> str:
    """Return the ID of the device registered for the given config entry."""
    [device] = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return device.id


async def _async_ems_entry(
    hass, mock_modbus_unit, allow_control: bool
) -> AsyncGenerator[MockConfigEntry]:
    """Add a loaded config entry connected to the in-memory unit."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Wallbox", options={CONF_ALLOW_CONTROL: allow_control}
    )
    entry.add_to_hass(hass)
    coordinator = KathreinCoordinator(hass, entry, mock_modbus_unit)
    await coordinator.identity.async_update()
    mock_modbus_unit.holding[EMS_CONTROL_ADDRESS] = 0x8000
    await coordinator.ems_control.async_update()
    entry.runtime_data = WallboxRuntimeData(coordinator=coordinator)
    entry.mock_state(hass, ConfigEntryState.LOADED)
    _async_add_device(hass, entry)
    await async_setup(hass, {})
    yield entry
    # Writes schedule a debounced refresh that must not outlive the test.
    await coordinator.async_shutdown()


@pytest.fixture
async def ems_entry(hass, mock_modbus_unit) -> AsyncGenerator[MockConfigEntry]:
    """Add a loaded config entry that allows control by Home Assistant."""
    async for entry in _async_ems_entry(hass, mock_modbus_unit, True):
        yield entry


@pytest.fixture
async def read_only_entry(hass, mock_modbus_unit) -> AsyncGenerator[MockConfigEntry]:
    """Add a loaded config entry that does not allow control by Home Assistant."""
    async for entry in _async_ems_entry(hass, mock_modbus_unit, False):
        yield entry


async def _async_call(hass, entry, service, service_data) -> None:
    """Call a Wallbox service for the device of the given config entry."""
    await hass.services.async_call(
        DOMAIN,
        service,
        {"device_id": _device_id(hass, entry), **service_data},
        blocking=True,
    )


@pytest.mark.parametrize(
    ("service", "service_data", "address", "value"),
    [
        (SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": True}, 0x00A0, 0x8000),
        (SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": False}, 0x00A0, 0),
        (SERVICE_SET_RELAY_MATRIX, {"value": "phase_1"}, 0x00A1, 1),
        (SERVICE_SET_RELAY_MATRIX, {"value": "three_phases"}, 0x00A1, 7),
        (SERVICE_SET_CHARGING_CURRENT, {"value": "20"}, 0x00A2, 20000),
        (SERVICE_SET_CHARGING_CURRENT, {"value": "0"}, 0x00A2, 0),
        (SERVICE_SET_CHARGING_CURRENT, {"value": 6}, 0x00A2, 6000),
        (SERVICE_SET_CHARGING_CURRENT, {"value": 13}, 0x00A2, 13000),
        (SERVICE_SET_CHARGING_CURRENT, {"value": 32.0}, 0x00A2, 32000),
        (SERVICE_SET_TIMEOUT_PERIOD, {"value": "60"}, 0x00A3, 60),
        (
            SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX,
            {"value": "three_phases"},
            0x00A4,
            7,
        ),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, {"value": "0"}, 0x00A5, 0),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, {"value": 7}, 0x00A5, 7000),
    ],
)
async def test_ems_services_write_expected_register(
    hass, mock_modbus_unit, ems_entry, service, service_data, address, value
) -> None:
    """Write each supported EMS command to its documented register."""
    await _async_call(hass, ems_entry, service, service_data)

    writes = [(address, [value])]
    if service in (SERVICE_SET_RELAY_MATRIX, SERVICE_SET_CHARGING_CURRENT):
        writes.insert(0, (EMS_CONTROL_ADDRESS, [0x8000]))
    assert _writes(mock_modbus_unit) == writes


@pytest.mark.parametrize(
    ("service", "service_data"),
    [
        (SERVICE_SET_RELAY_MATRIX, {"value": "phase_1"}),
        (SERVICE_SET_CHARGING_CURRENT, {"value": 13}),
        (SERVICE_SET_TIMEOUT_PERIOD, {"value": "60"}),
        (SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX, {"value": "three_phases"}),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, {"value": 7}),
    ],
)
async def test_ems_services_need_control_allowed(
    hass, mock_modbus_unit, read_only_entry, service, service_data
) -> None:
    """Reject setpoint services without writing while control is not allowed."""
    with pytest.raises(ServiceValidationError) as error:
        await _async_call(hass, read_only_entry, service, service_data)

    assert error.value.translation_key == "control_not_allowed"
    assert mock_modbus_unit.write_events == []


@pytest.mark.parametrize(
    ("service", "value"),
    [
        (SERVICE_SET_RELAY_MATRIX, "line_1"),
        (SERVICE_SET_RELAY_MATRIX, "phase_2"),
        (SERVICE_SET_RELAY_MATRIX, "three_lines"),
        (SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX, "phase_3"),
        (SERVICE_SET_CHARGING_CURRENT, 33),
        (SERVICE_SET_CHARGING_CURRENT, 16.5),
        (SERVICE_SET_CHARGING_CURRENT, "fast"),
        (SERVICE_SET_TIMEOUT_PERIOD, "45"),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, "40"),
    ],
)
async def test_ems_services_reject_unsupported_values(
    hass, mock_modbus_unit, ems_entry, service, value
) -> None:
    """Reject values the Wallbox does not support before writing anything."""
    with pytest.raises(probatio.Invalid):
        await _async_call(hass, ems_entry, service, {"value": value})

    assert mock_modbus_unit.write_events == []


@pytest.mark.parametrize(
    "service", [SERVICE_SET_CHARGING_CURRENT, SERVICE_SET_TIMEOUT_FALLBACK_CURRENT]
)
@pytest.mark.parametrize("value", [1, "5"])
async def test_ems_services_reject_current_below_minimum(
    hass, mock_modbus_unit, ems_entry, service, value
) -> None:
    """Reject 1 to 5 A with a clear error instead of writing a register."""
    with pytest.raises(ServiceValidationError) as error:
        await _async_call(hass, ems_entry, service, {"value": value})

    assert error.value.translation_key == "current_below_minimum"
    assert error.value.translation_placeholders == {"min_current": "6"}
    assert mock_modbus_unit.write_events == []


@pytest.mark.parametrize(
    ("service", "value", "address"),
    [
        (SERVICE_SET_CHARGING_CURRENT, "16", 0x00A2),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, "16", 0x00A5),
    ],
)
async def test_11_kw_wallbox_accepts_maximum_ems_current(
    hass, mock_modbus_unit, ems_entry, service, value, address
) -> None:
    """Allow exactly 16 A on an 11 kW wallbox."""
    mock_modbus_unit.holding[DEVICE_INFO_ADDRESS] = DEVICE_INFO_11_KW
    await ems_entry.runtime_data.coordinator.identity.async_update()

    await _async_call(hass, ems_entry, service, {"value": value})

    assert _writes(mock_modbus_unit)[-1] == (address, [16000])


@pytest.mark.parametrize(
    "service", [SERVICE_SET_CHARGING_CURRENT, SERVICE_SET_TIMEOUT_FALLBACK_CURRENT]
)
async def test_11_kw_wallbox_rejects_ems_current_above_limit(
    hass, mock_modbus_unit, ems_entry, service
) -> None:
    """Reject current values above 16 A without writing a register."""
    mock_modbus_unit.holding[DEVICE_INFO_ADDRESS] = DEVICE_INFO_11_KW
    await ems_entry.runtime_data.coordinator.identity.async_update()

    with pytest.raises(ServiceValidationError) as error:
        await _async_call(hass, ems_entry, service, {"value": "20"})

    assert error.value.translation_key == "current_limit_11_kw"
    assert mock_modbus_unit.write_events == []


def _other_device_id(hass) -> str:
    """Return the ID of a device that belongs to another integration."""
    entry = MockConfigEntry(domain="other")
    entry.add_to_hass(hass)
    return _async_add_device(hass, entry).id


@pytest.mark.parametrize(
    "device_id",
    [lambda hass: "missing-device", _other_device_id],
    ids=["unknown", "other_integration"],
)
async def test_ems_service_rejects_device_that_is_no_wallbox(
    hass, mock_modbus_unit, ems_entry, device_id
) -> None:
    """Reject service calls that do not refer to a wallbox device."""
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_RELAY_MATRIX,
            {"device_id": device_id(hass), "value": "phase_1"},
            blocking=True,
        )

    assert error.value.translation_key == "device_not_found"
    assert mock_modbus_unit.write_events == []


async def test_ems_service_rejects_entry_that_is_not_loaded(
    hass, mock_modbus_unit, ems_entry
) -> None:
    """Reject service calls for a wallbox entry that failed to set up."""
    ems_entry.mock_state(hass, ConfigEntryState.SETUP_RETRY)

    with pytest.raises(ServiceValidationError) as error:
        await _async_call(
            hass, ems_entry, SERVICE_SET_RELAY_MATRIX, {"value": "phase_1"}
        )

    assert error.value.translation_key == "entry_not_loaded"
    assert mock_modbus_unit.write_events == []


async def test_ems_service_reports_device_write_failure(
    hass, mock_modbus_unit, ems_entry
) -> None:
    """Surface a failed register write as a Home Assistant error."""
    mock_modbus_unit.fail_write(0x00A1, ModbusError("write rejected"))

    with pytest.raises(HomeAssistantError) as error:
        await _async_call(
            hass, ems_entry, SERVICE_SET_RELAY_MATRIX, {"value": "phase_1"}
        )

    assert error.value.translation_key == "write_failed"


@pytest.mark.parametrize(
    ("service", "value"),
    [
        (SERVICE_SET_TIMEOUT_PERIOD, "60"),
        (SERVICE_SET_TIMEOUT_FALLBACK_RELAY_MATRIX, "three_phases"),
        (SERVICE_SET_TIMEOUT_FALLBACK_CURRENT, 7),
    ],
)
async def test_ems_timeout_services_reject_disabled_ems_control(
    hass, mock_modbus_unit, ems_entry, service, value
) -> None:
    """Reject timeout settings without writing while EMS control is off."""
    coordinator = ems_entry.runtime_data.coordinator
    mock_modbus_unit.holding[EMS_CONTROL_ADDRESS] = 0
    await coordinator.ems_control.async_update()

    with pytest.raises(ServiceValidationError) as error:
        await _async_call(hass, ems_entry, service, {"value": value})

    assert error.value.translation_key == "ems_control_disabled"
    assert mock_modbus_unit.write_events == []


async def test_ems_control_service_enables_disabled_ems_control(
    hass, mock_modbus_unit, ems_entry
) -> None:
    """Keep EMS control itself switchable while it is off."""
    coordinator = ems_entry.runtime_data.coordinator
    mock_modbus_unit.holding[EMS_CONTROL_ADDRESS] = 0
    await coordinator.ems_control.async_update()

    await _async_call(
        hass, ems_entry, SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": True}
    )

    assert _writes(mock_modbus_unit) == [(EMS_CONTROL_ADDRESS, [0x8000])]


@pytest.mark.parametrize(
    ("service", "value", "address", "register"),
    [
        (SERVICE_SET_RELAY_MATRIX, "phase_1", 0x00A1, 1),
        (SERVICE_SET_CHARGING_CURRENT, 13, 0x00A2, 13000),
    ],
)
async def test_ems_setpoint_services_enable_disabled_ems_control(
    hass, mock_modbus_unit, ems_entry, service, value, address, register
) -> None:
    """Enable EMS control before writing a setpoint while it is off."""
    coordinator = ems_entry.runtime_data.coordinator
    mock_modbus_unit.holding[EMS_CONTROL_ADDRESS] = 0
    await coordinator.ems_control.async_update()

    await _async_call(hass, ems_entry, service, {"value": value})

    assert _writes(mock_modbus_unit) == [
        (EMS_CONTROL_ADDRESS, [0x8000]),
        (address, [register]),
    ]


@pytest.mark.parametrize(("enabled", "value"), [(True, 0x8000), (False, 0)])
async def test_ems_control_service_works_without_control_allowed(
    hass, mock_modbus_unit, read_only_entry, enabled, value
) -> None:
    """Switch EMS control even while control by Home Assistant is not allowed."""
    await _async_call(
        hass, read_only_entry, SERVICE_SET_EMS_CONTROL_ENABLED, {"enabled": enabled}
    )

    assert _writes(mock_modbus_unit) == [(EMS_CONTROL_ADDRESS, [value])]
