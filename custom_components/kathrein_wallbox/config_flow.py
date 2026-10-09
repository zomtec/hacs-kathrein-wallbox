"""Config flow for Kathrein Wallbox."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.modbus import async_get_temporary_unit
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from modbus_connection import ModbusError, ModbusTcpParams
import voluptuous as vol

from .const import (
    CONF_SCAN_INTERVAL,
    CONF_UNIT_ID,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_UNIT_ID,
    DOMAIN,
    EXPECTED_MAPPING_VERSION,
    MIN_PORT,
    MAX_PORT,
    MIN_UNIT_ID,
    MAX_UNIT_ID,
    MIN_SCAN_INTERVAL_SECONDS,
    MAX_SCAN_INTERVAL_SECONDS
)
from .model import WallboxIdentity

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_PORT,
                max=MAX_PORT,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_UNIT_ID, default=DEFAULT_UNIT_ID): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_UNIT_ID,
                max=MAX_UNIT_ID,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL.seconds): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=MIN_SCAN_INTERVAL_SECONDS,
                max=MAX_SCAN_INTERVAL_SECONDS,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }
)


class InvalidWallbox(Exception):
    """Raised when the device does not report a supported mapping."""


def _normalize_connection_data(user_input: dict[str, Any]) -> dict[str, Any]:
    """Normalize numeric connection settings returned by number selectors."""
    normalized = dict(user_input)
    for key in (CONF_PORT, CONF_UNIT_ID, CONF_SCAN_INTERVAL):
        if key in normalized:
            normalized[key] = int(normalized[key])
    return normalized


async def _async_validate_input(
    hass: HomeAssistant, user_input: dict[str, Any]
) -> tuple[str, str]:
    """Check the mapping version and retrieve the device identity."""
    connection_data = _normalize_connection_data(user_input)
    params = ModbusTcpParams(
        host=connection_data[CONF_HOST],
        port=connection_data[CONF_PORT],
    )
    async with async_get_temporary_unit(
        hass, params, connection_data[CONF_UNIT_ID]
    ) as unit:
        identity = WallboxIdentity(unit)
        await identity.async_update()

    if identity.mapping_version != EXPECTED_MAPPING_VERSION or not identity.serial:
        raise InvalidWallbox
    return identity.serial, identity.device_type or "Kathrein Wallbox"


class KathreinWallboxConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a user-configured Wallbox."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow for adjusting the polling interval."""
        return KathreinWallboxOptionsFlowHandler()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Validate the connection and create a config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                serial, device_type = await _async_validate_input(self.hass, user_input)
            except InvalidWallbox:
                errors["base"] = "unsupported_device"
            except (HomeAssistantError, ModbusError):
                _LOGGER.exception("Unable to connect to the Kathrein Wallbox")
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=device_type,
                    data=_normalize_connection_data(user_input),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Allow changing the connection parameters after the initial setup."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                serial, device_type = await _async_validate_input(self.hass, user_input)
            except InvalidWallbox:
                errors["base"] = "unsupported_device"
            except (HomeAssistantError, ModbusError):
                _LOGGER.exception("Unable to connect to the Kathrein Wallbox")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates=_normalize_connection_data(user_input),
                    options={},
                    title=device_type,
                )

        current = entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str,
                    vol.Optional(CONF_PORT, default=current.get(CONF_PORT, DEFAULT_PORT)): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_PORT,
                            max=MAX_PORT,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_UNIT_ID,
                        default=current.get(CONF_UNIT_ID, DEFAULT_UNIT_ID),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_UNIT_ID,
                            max=MAX_UNIT_ID,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=current.get(
                            CONF_SCAN_INTERVAL,
                            DEFAULT_SCAN_INTERVAL.seconds,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_SECONDS,
                            max=MAX_SCAN_INTERVAL_SECONDS,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                }
            ),
            errors=errors,
        )


class KathreinWallboxOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle connection settings after initial setup."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Edit and validate all connection settings from the options menu."""
        errors: dict[str, str] = {}
        if user_input is not None:
            connection_data = _normalize_connection_data(user_input)
            try:
                await _async_validate_input(self.hass, connection_data)
            except InvalidWallbox:
                errors["base"] = "unsupported_device"
            except (HomeAssistantError, ModbusError):
                _LOGGER.exception("Unable to connect to the Kathrein Wallbox")
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data=connection_data,
                    options={},
                )
                self.hass.config_entries.async_schedule_reload(
                    self.config_entry.entry_id
                )
                return self.async_create_entry(title="", data={})

        current = self.config_entry.data
        scan_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL.seconds),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=current.get(CONF_HOST, "")): str,
                    vol.Required(
                        CONF_PORT,
                        default=current.get(CONF_PORT, DEFAULT_PORT),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_PORT,
                            max=MAX_PORT,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_UNIT_ID,
                        default=current.get(CONF_UNIT_ID, DEFAULT_UNIT_ID),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_UNIT_ID,
                            max=MAX_UNIT_ID,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=scan_interval,
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_SECONDS,
                            max=MAX_SCAN_INTERVAL_SECONDS,
                            step=1,
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    )
                }
            ),
            errors=errors,
        )
