"""Tests for the invalid phase rotation repair issue."""

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.kathrein_wallbox.const import DOMAIN
from custom_components.kathrein_wallbox.model import LINE_MAPPING_ADDRESS


def _issue(hass, entry) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(
        DOMAIN, f"invalid_phase_rotation_{entry.entry_id}"
    )


@pytest.mark.parametrize(
    ("line_mapping", "expected"),
    [(1, "L1-L3-L2"), (3, "L2-L1-L3"), (5, "L3-L2-L1")],
)
async def test_invalid_phase_rotation_creates_issue(
    hass, entry, mock_modbus_unit, setup_integration, line_mapping, expected
) -> None:
    """Raise a repair issue naming the reported invalid line mapping."""
    mock_modbus_unit.holding[LINE_MAPPING_ADDRESS] = line_mapping
    await setup_integration()

    issue = _issue(hass, entry)
    assert issue is not None
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert issue.translation_key == "invalid_phase_rotation"
    assert issue.translation_placeholders == {
        "title": entry.title,
        "line_mapping": expected,
    }


@pytest.mark.parametrize("line_mapping", [0, 2, 4])
async def test_valid_phase_rotation_creates_no_issue(
    hass, entry, mock_modbus_unit, setup_integration, line_mapping
) -> None:
    """Leave valid line mappings without a repair issue."""
    mock_modbus_unit.holding[LINE_MAPPING_ADDRESS] = line_mapping
    await setup_integration()

    assert _issue(hass, entry) is None


async def test_reload_with_valid_phase_rotation_removes_issue(
    hass, entry, mock_modbus_unit, setup_integration
) -> None:
    """Check the phase rotation again when the integration is reloaded."""
    mock_modbus_unit.holding[LINE_MAPPING_ADDRESS] = 1
    await setup_integration()
    assert _issue(hass, entry) is not None
    mock_modbus_unit.holding[LINE_MAPPING_ADDRESS] = 0

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, entry) is None


async def test_removing_entry_removes_issue(
    hass, entry, mock_modbus_unit, setup_integration
) -> None:
    """Drop the repair issue together with the Wallbox."""
    mock_modbus_unit.holding[LINE_MAPPING_ADDRESS] = 1
    await setup_integration()
    assert _issue(hass, entry) is not None

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert _issue(hass, entry) is None
