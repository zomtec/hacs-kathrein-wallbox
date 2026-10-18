"""Kathrein Wallbox integration setup."""

from homeassistant.components.modbus import async_get_unit
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.typing import ConfigType
from modbus_connection import ModbusTcpParams

from .const import CONF_UNIT_ID, DOMAIN, PLATFORMS, get_scan_interval
from .coordinator import KathreinConfigEntry, KathreinCoordinator, WallboxRuntimeData
from .entity import wallbox_unique_id
from .model import WallboxIdentity
from .number import CHARGING_CURRENT_DESCRIPTION
from .select import RELAY_MATRIX_DESCRIPTION
from .services import async_setup_services

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

ISSUE_INVALID_PHASE_ROTATION = "invalid_phase_rotation"

CONTROL_ENTITY_KEYS = (
    CHARGING_CURRENT_DESCRIPTION.key,
    RELAY_MATRIX_DESCRIPTION.key,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Kathrein Wallbox integration."""
    async_setup_services(hass)
    return True


@callback
def _async_sync_control_entities(
    hass: HomeAssistant, entry: KathreinConfigEntry, serial: str, allowed: bool
) -> None:
    """Disable control entities unless control is allowed, sparing user choices."""
    registry = er.async_get(hass)
    control_unique_ids = {wallbox_unique_id(serial, key) for key in CONTROL_ENTITY_KEYS}
    by_integration = er.RegistryEntryDisabler.INTEGRATION
    current, target = (by_integration, None) if allowed else (None, by_integration)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            entity_entry.unique_id in control_unique_ids
            and entity_entry.disabled_by is current
        ):
            registry.async_update_entity(entity_entry.entity_id, disabled_by=target)


def _phase_rotation_issue_id(entry: KathreinConfigEntry) -> str:
    """Return the repair issue ID for the phase rotation of one Wallbox."""
    return f"{ISSUE_INVALID_PHASE_ROTATION}_{entry.entry_id}"


@callback
def _async_check_phase_rotation(
    hass: HomeAssistant, entry: KathreinConfigEntry, identity: WallboxIdentity
) -> None:
    """Raise a repair issue while the Wallbox reports an invalid phase rotation."""
    issue_id = _phase_rotation_issue_id(entry)
    line_mapping = identity.invalid_phase_rotation
    if line_mapping is None:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_INVALID_PHASE_ROTATION,
        translation_placeholders={
            "title": entry.title,
            "line_mapping": line_mapping.name.replace("_", "-"),
        },
    )


async def async_setup_entry(hass: HomeAssistant, entry: KathreinConfigEntry) -> bool:
    """Set up a Wallbox config entry."""
    params = ModbusTcpParams(
        host=entry.data[CONF_HOST],
        port=int(entry.data[CONF_PORT]),
    )
    unit = async_get_unit(hass, entry, params, int(entry.data[CONF_UNIT_ID]))
    coordinator = KathreinCoordinator(
        hass,
        entry,
        unit,
        update_interval=get_scan_interval(entry),
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = WallboxRuntimeData(coordinator=coordinator)
    _async_sync_control_entities(
        hass, entry, coordinator.serial, coordinator.control_allowed
    )
    _async_check_phase_rotation(hass, entry, coordinator.device.identity)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: KathreinConfigEntry) -> bool:
    """Unload platforms for a Wallbox config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: KathreinConfigEntry) -> None:
    """Remove the repair issue of a deleted Wallbox."""
    ir.async_delete_issue(hass, DOMAIN, _phase_rotation_issue_id(entry))
