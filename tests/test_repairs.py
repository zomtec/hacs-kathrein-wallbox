"""Tests for the invalid phase rotation repair issue."""

from unittest.mock import Mock

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.kathrein_wallbox.const import CONF_UNIT_ID, DOMAIN
from custom_components.kathrein_wallbox.model import LINE_MAPPING_ADDRESS


@pytest.fixture
def entry(
    hass, monkeypatch, mock_modbus_unit, enable_custom_integrations
) -> MockConfigEntry:
    """Add a Wallbox entry that talks to the in-memory unit."""
    monkeypatch.setattr(
        "custom_components.kathrein_wallbox.async_get_unit",
        Mock(return_value=mock_modbus_unit),
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Garage",
        data={CONF_HOST: "wallbox.local", CONF_PORT: 502, CONF_UNIT_ID: 0},
    )
    entry.add_to_hass(hass)
    return entry


def _issue(hass, entry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"invalid_phase_rotation_{entry.entry_id}"
    )


async def _async_setup_with_line_mapping(
    hass, entry, mock_modbus_unit, line_mapping: int
) -> None:
    mock_modbus_unit.holding[LINE_MAPPING_ADDRESS] = line_mapping
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("line_mapping", "expected"),
    [(1, "L1-L3-L2"), (3, "L2-L1-L3"), (5, "L3-L2-L1")],
)
async def test_invalid_phase_rotation_creates_issue(
    hass, entry, mock_modbus_unit, line_mapping, expected
) -> None:
    """Raise a repair issue naming the reported invalid line mapping."""
    await _async_setup_with_line_mapping(hass, entry, mock_modbus_unit, line_mapping)

    issue = _issue(hass, entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert issue.translation_key == "invalid_phase_rotation"
    assert issue.translation_placeholders == {
        "title": "Garage",
        "line_mapping": expected,
    }


@pytest.mark.parametrize("line_mapping", [0, 2, 4])
async def test_valid_phase_rotation_creates_no_issue(
    hass, entry, mock_modbus_unit, line_mapping
) -> None:
    """Leave valid line mappings without a repair issue."""
    await _async_setup_with_line_mapping(hass, entry, mock_modbus_unit, line_mapping)

    assert _issue(hass, entry) is None


async def test_reload_with_valid_phase_rotation_removes_issue(
    hass, entry, mock_modbus_unit
) -> None:
    """Check the phase rotation again when the integration is reloaded."""
    await _async_setup_with_line_mapping(hass, entry, mock_modbus_unit, 1)
    mock_modbus_unit.holding[LINE_MAPPING_ADDRESS] = 0

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, entry) is None


async def test_removing_entry_removes_issue(hass, entry, mock_modbus_unit) -> None:
    """Drop the repair issue together with the Wallbox."""
    await _async_setup_with_line_mapping(hass, entry, mock_modbus_unit, 1)

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, entry) is None
