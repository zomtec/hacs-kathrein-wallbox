"""Tests for the Kathrein Wallbox config flow."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_DHCP, SOURCE_USER
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from modbus_connection import ModbusError
from modbus_connection.encode import encode_string
from modbus_connection.mock import MockModbusUnit
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox import config_flow
from custom_components.kathrein_wallbox.const import (
    DEVICE_NAME,
    DOMAIN,
    EXPECTED_MAPPING_VERSION,
)
from custom_components.kathrein_wallbox.model import (
    DEVICE_TYPE_ADDRESS,
    MAPPING_VERSION_ADDRESS,
    SERIAL_ADDRESS,
    SERIAL_REGISTER_COUNT,
)


async def test_user_flow_creates_entry_with_normalized_connection_data(
    hass, monkeypatch, enable_custom_integrations
) -> None:
    """Store connection data as whole numbers and keep control off by default."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("SERIAL123", "Kathrein 11 kW")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "host": "wallbox.local",
            "port": 502.0,
            "unit_id": 1.0,
            "scan_interval": 20.0,
        },
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "Kathrein 11 kW"
    assert result["data"] == {
        "host": "wallbox.local",
        "port": 502,
        "unit_id": 1,
    }
    assert result["options"] == {"scan_interval": 20, "allow_control": False}


@pytest.mark.parametrize(
    ("error_type", "expected_error"),
    [
        (config_flow.InvalidWallbox, "unsupported_device"),
        (HomeAssistantError, "cannot_connect"),
        (ModbusError, "cannot_connect"),
    ],
)
async def test_user_flow_reports_validation_errors(
    hass, monkeypatch, enable_custom_integrations, error_type, expected_error
) -> None:
    """Show a distinct form error for unsupported and unreachable devices."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(side_effect=error_type("test failure")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "wallbox.local"}
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": expected_error}


CONNECTION = {
    "host": "wallbox.local",
    "port": 502,
    "unit_id": 1,
}
OPTIONS = {"scan_interval": 20, "allow_control": True}
NEW_CONNECTION = {**CONNECTION, "host": "new-wallbox.local"}


@pytest.fixture
def wallbox_entry(hass, enable_custom_integrations) -> MockConfigEntry:
    """Add a configured Wallbox entry whose setup is not exercised."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="SERIAL123",
        data=CONNECTION,
        options=OPTIONS,
        title="Kathrein",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture(autouse=True)
def skip_entry_setup():
    """Avoid loading the integration when a flow reloads its entry."""
    with patch(
        "custom_components.kathrein_wallbox.async_setup_entry", return_value=True
    ):
        yield


async def test_user_flow_aborts_for_already_configured_wallbox(
    hass, monkeypatch, wallbox_entry
) -> None:
    """Prevent configuring the same Wallbox twice."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("SERIAL123", "Kathrein 11 kW")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"


async def test_reconfigure_updates_connection_data(
    hass, monkeypatch, wallbox_entry
) -> None:
    """Store the new connection settings and keep the polling interval."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("SERIAL123", "Kathrein 22 kW")),
    )
    result = await wallbox_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert wallbox_entry.data == NEW_CONNECTION
    assert wallbox_entry.options == OPTIONS
    assert wallbox_entry.title == "Kathrein 22 kW"


async def test_reconfigure_aborts_for_a_different_wallbox(
    hass, monkeypatch, wallbox_entry
) -> None:
    """Refuse to repoint an entry to another Wallbox."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(return_value=("OTHER", "Kathrein 11 kW")),
    )
    result = await wallbox_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "abort"
    assert result["reason"] == "unique_id_mismatch"
    assert wallbox_entry.data == CONNECTION


@pytest.mark.parametrize(
    ("error_type", "expected_error"),
    [
        (config_flow.InvalidWallbox, "unsupported_device"),
        (ModbusError, "cannot_connect"),
    ],
)
async def test_reconfigure_reports_validation_errors(
    hass, monkeypatch, wallbox_entry, error_type, expected_error
) -> None:
    """Keep the form open and show the matching error."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(side_effect=error_type("test failure")),
    )
    result = await wallbox_entry.start_reconfigure_flow(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], NEW_CONNECTION
    )

    assert result["type"] == "form"
    assert result["errors"] == {"base": expected_error}


async def test_options_flow_offers_polling_and_control(hass, wallbox_entry) -> None:
    """Leave connection settings to reconfigure and prefill the current options."""
    result = await hass.config_entries.options.async_init(wallbox_entry.entry_id)

    assert result["type"] == "form"
    assert list(result["data_schema"].schema) == ["scan_interval", "allow_control"]
    assert result["data_schema"]({}) == OPTIONS


async def test_options_flow_defaults_to_no_control(
    hass, enable_custom_integrations
) -> None:
    """Prefill control as not allowed for an entry without that option."""
    entry = MockConfigEntry(domain=DOMAIN, data=CONNECTION, options={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["data_schema"]({})["allow_control"] is False


async def test_options_flow_updates_options(hass, wallbox_entry) -> None:
    """Store the new options without touching the connection data."""
    result = await hass.config_entries.options.async_init(wallbox_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"scan_interval": 30.0, "allow_control": False}
    )

    assert result["type"] == "create_entry"
    assert wallbox_entry.options == {"scan_interval": 30, "allow_control": False}
    assert wallbox_entry.data == CONNECTION


DEVICE_TYPE_REGISTERS = [0x4B57, 0x422D, 0x4143, 0x3131]


@pytest.fixture
def wallbox_unit(mock_modbus_unit) -> MockModbusUnit:
    """Serve a supported Wallbox through the flow's temporary Modbus unit."""
    mock_modbus_unit.holding[MAPPING_VERSION_ADDRESS] = [EXPECTED_MAPPING_VERSION]
    mock_modbus_unit.holding[DEVICE_TYPE_ADDRESS] = DEVICE_TYPE_REGISTERS

    @asynccontextmanager
    async def temporary_unit(hass, params, unit_id) -> AsyncIterator[MockModbusUnit]:
        assert (params.host, params.port, unit_id) == ("wallbox.local", 502, 1)
        yield mock_modbus_unit

    with patch.object(config_flow, "async_get_temporary_unit", temporary_unit):
        yield mock_modbus_unit


def _report_wrong_mapping(unit: MockModbusUnit) -> None:
    unit.holding[MAPPING_VERSION_ADDRESS] = [EXPECTED_MAPPING_VERSION + 1]


def _report_no_serial(unit: MockModbusUnit) -> None:
    unit.holding[SERIAL_ADDRESS] = [0] * SERIAL_REGISTER_COUNT


def _fail_requests(unit: MockModbusUnit) -> None:
    unit.fail_requests(ModbusError("connection refused"))


def _repair(unit: MockModbusUnit, serial: str) -> None:
    unit.fail_requests(None)
    unit.holding[MAPPING_VERSION_ADDRESS] = [EXPECTED_MAPPING_VERSION]
    unit.holding[SERIAL_ADDRESS] = encode_string(serial, length=SERIAL_REGISTER_COUNT)


DEVICE_FAILURES = pytest.mark.parametrize(
    ("break_device", "expected_error"),
    [
        (_report_wrong_mapping, "unsupported_device"),
        (_report_no_serial, "unsupported_device"),
        (_fail_requests, "cannot_connect"),
    ],
)


async def test_user_flow_reads_the_device_identity(
    hass, enable_custom_integrations, wallbox_unit, serial
) -> None:
    """Use the serial as unique ID and the reported device type as title."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONNECTION
    )

    assert result["type"] == "create_entry"
    assert result["title"] == "KWB-AC11"
    assert result["result"].unique_id == serial


async def test_user_flow_falls_back_to_the_default_title(
    hass, enable_custom_integrations, wallbox_unit
) -> None:
    """Name the entry generically when the device reports no type."""
    del wallbox_unit.holding[DEVICE_TYPE_ADDRESS]
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONNECTION
    )

    assert result["type"] == "create_entry"
    assert result["title"] == DEVICE_NAME


@DEVICE_FAILURES
async def test_user_flow_recovers_after_device_error(
    hass,
    enable_custom_integrations,
    wallbox_unit,
    serial,
    break_device: Callable[[MockModbusUnit], None],
    expected_error: str,
) -> None:
    """Show the error, then create the entry once the device answers correctly."""
    break_device(wallbox_unit)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONNECTION
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": expected_error}

    _repair(wallbox_unit, serial)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONNECTION
    )

    assert result["type"] == "create_entry"
    assert result["result"].unique_id == serial


@DEVICE_FAILURES
async def test_reconfigure_recovers_after_device_error(
    hass,
    enable_custom_integrations,
    wallbox_unit,
    serial,
    break_device: Callable[[MockModbusUnit], None],
    expected_error: str,
) -> None:
    """Show the error, then update the entry once the device answers correctly."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=serial,
        data={**CONNECTION, "host": "old-wallbox.local"},
        options=OPTIONS,
        title="Kathrein",
    )
    entry.add_to_hass(hass)
    break_device(wallbox_unit)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONNECTION
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": expected_error}

    _repair(wallbox_unit, serial)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], CONNECTION
    )

    assert result["type"] == "abort"
    assert result["reason"] == "reconfigure_successful"
    assert entry.data == CONNECTION
    assert entry.title == "KWB-AC11"


DISCOVERED_IP = "192.0.2.20"


def _dhcp_info(serial: str) -> DhcpServiceInfo:
    return DhcpServiceInfo(
        ip=DISCOVERED_IP, hostname=f"kwb{serial.lower()}", macaddress="00d055000001"
    )


async def test_dhcp_discovery_creates_entry_after_confirmation(
    hass, monkeypatch, enable_custom_integrations, serial
) -> None:
    """Read the discovered address and keep control off by default."""
    validate = AsyncMock(return_value=(serial, "KWB-AC11"))
    monkeypatch.setattr(config_flow, "_async_validate_input", validate)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=_dhcp_info(serial)
    )
    assert result["type"] == "form"
    assert result["step_id"] == "dhcp_confirm"
    assert result["description_placeholders"] == {"host": DISCOVERED_IP}

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"port": 502.0, "unit_id": 1.0}
    )

    assert result["type"] == "create_entry"
    assert result["result"].unique_id == serial
    assert result["data"] == {"host": DISCOVERED_IP, "port": 502, "unit_id": 1}
    assert result["options"] == {"scan_interval": 15, "allow_control": False}
    assert validate.await_args.args[1]["host"] == DISCOVERED_IP


OTHER_SERIAL = "G0R7654321"
CONNECTION_REFUSED = ModbusError("connection refused")


@pytest.mark.parametrize(
    ("stored_host_answer", "discovered_ip_answer", "expected_host"),
    [
        (CONNECTION_REFUSED, "SERIAL123", DISCOVERED_IP),
        ("SERIAL123", "SERIAL123", "wallbox.local"),
        (CONNECTION_REFUSED, CONNECTION_REFUSED, "wallbox.local"),
        (CONNECTION_REFUSED, OTHER_SERIAL, "wallbox.local"),
    ],
    ids=["moved", "stored-host-answers", "no-answer-at-ip", "other-wallbox-at-ip"],
)
async def test_dhcp_discovery_updates_address_only_after_a_move(
    hass,
    monkeypatch,
    wallbox_entry,
    stored_host_answer: str | ModbusError,
    discovered_ip_answer: str | ModbusError,
    expected_host: str,
) -> None:
    """Keep a working host such as a Modbus proxy and follow only a moved Wallbox."""
    answers = {"wallbox.local": stored_host_answer, DISCOVERED_IP: discovered_ip_answer}

    async def validate(hass, connection_data) -> tuple[str, str]:
        assert (connection_data["port"], connection_data["unit_id"]) == (502, 1)
        answer = answers[connection_data["host"]]
        if isinstance(answer, ModbusError):
            raise answer
        return answer, "KWB-AC11"

    monkeypatch.setattr(config_flow, "_async_validate_input", validate)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=_dhcp_info("SERIAL123")
    )

    assert result["type"] == "abort"
    assert result["reason"] == "already_configured"
    assert wallbox_entry.data == {**CONNECTION, "host": expected_host}


async def test_dhcp_confirmation_reports_validation_errors(
    hass, monkeypatch, enable_custom_integrations, serial
) -> None:
    """Keep the confirmation form open when the Wallbox cannot be read."""
    monkeypatch.setattr(
        config_flow,
        "_async_validate_input",
        AsyncMock(side_effect=ModbusError("connection refused")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_DHCP}, data=_dhcp_info(serial)
    )

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] == "form"
    assert result["errors"] == {"base": "cannot_connect"}
