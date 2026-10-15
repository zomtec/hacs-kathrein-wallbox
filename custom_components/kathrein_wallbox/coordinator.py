"""Polling coordinator for Kathrein Wallbox register data."""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from modbus_connection import ModbusError, ModbusUnit

from .const import DEFAULT_SCAN_INTERVAL, DEVICE_NAME, DOMAIN, get_allow_control
from .model import (
    WallboxEMSControl,
    WallboxEVSE,
    WallboxIdentity,
    WallboxMeter,
    WallboxSessionEnergy,
)

_LOGGER = logging.getLogger(__name__)

# Rewrite the setpoint twice per timeout period so one missed write is tolerated.
KEEP_ALIVE_WRITES_PER_TIMEOUT = 2
# Never rewrite the setpoint more often than this, whatever the EMS timeout.
KEEP_ALIVE_MIN_INTERVAL = timedelta(seconds=5)


class KathreinCoordinator(DataUpdateCoordinator["WallboxData"]):
    """Fetch the Wallbox model at a fixed polling interval."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: KathreinConfigEntry,
        unit: ModbusUnit,
        update_interval: timedelta | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DEVICE_NAME,
            update_interval=update_interval or DEFAULT_SCAN_INTERVAL,
        )
        self.unit = unit
        self.identity = WallboxIdentity(unit)
        self.meter = WallboxMeter(unit)
        self.session_energy = WallboxSessionEnergy(unit)
        self.evse = WallboxEVSE(unit)
        self.ems_control = WallboxEMSControl(unit)
        self.meter_available = False
        self.session_energy_available = False
        self.control_allowed = get_allow_control(entry)
        self._keep_alive_interval: timedelta | None = None
        self._cancel_keep_alive: CALLBACK_TYPE | None = None
        self._keep_alive_failed = False

    async def _async_setup(self) -> None:
        """Read the static device identity once before the first poll."""
        try:
            await self.identity.async_update()
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        if not self.identity.serial:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="missing_serial_number",
            )

    async def _async_update_data(self) -> WallboxData:
        """Read essential registers and isolate the optional energy meter."""
        try:
            await self.evse.async_update()
            await self.ems_control.async_update()
        except ModbusError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"error": str(err)},
            ) from err

        self._async_schedule_keep_alive()

        try:
            await self.meter.async_update()
        except ModbusError as err:
            if self.meter_available:
                _LOGGER.warning(
                    "Energy meter registers are no longer available: %s", err
                )
            self.meter_available = False
            self.session_energy_available = False
        else:
            self.meter_available = self.meter.has_plausible_reference
            if self.meter_available:
                try:
                    await self.session_energy.async_update()
                except ModbusError as err:
                    if self.session_energy_available:
                        _LOGGER.warning(
                            "Session energy register is no longer available: %s", err
                        )
                    self.session_energy_available = False
                else:
                    self.session_energy_available = True
            else:
                self.session_energy_available = False

        return WallboxData(
            identity=self.identity,
            meter=self.meter,
            session_energy=self.session_energy,
            evse=self.evse,
            ems_control=self.ems_control,
        )

    async def async_write_ems(self, field: str, value: int) -> None:
        """Write an EMS control field, report device failures and refresh."""
        self.validate_control_allowed()
        try:
            await self.ems_control.write(field, value)
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        # A debounced refresh would delay the read-back of a quick second write.
        await self.async_refresh()

    def validate_control_allowed(self) -> None:
        """Reject writes unless the user allowed control by Home Assistant."""
        if not self.control_allowed:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="control_not_allowed",
            )

    async def async_shutdown(self) -> None:
        """Stop the keep-alive timer together with polling."""
        await super().async_shutdown()
        self._async_cancel_keep_alive()

    @callback
    def _async_schedule_keep_alive(self) -> None:
        """Run the keep-alive timer at a pace matching the current EMS timeout."""
        timeout_period = self.ems_control.timeout_period
        interval = None
        if self.control_allowed and timeout_period:
            interval = max(
                KEEP_ALIVE_MIN_INTERVAL,
                timedelta(seconds=timeout_period / KEEP_ALIVE_WRITES_PER_TIMEOUT),
            )
        if interval == self._keep_alive_interval:
            return
        self._async_cancel_keep_alive()
        if interval is None:
            return
        self._keep_alive_interval = interval
        self._cancel_keep_alive = async_track_time_interval(
            self.hass, self._async_keep_alive, interval, name="EMS keep-alive"
        )

    @callback
    def _async_cancel_keep_alive(self) -> None:
        """Stop the keep-alive timer if it runs."""
        if self._cancel_keep_alive is not None:
            self._cancel_keep_alive()
            self._cancel_keep_alive = None
        self._keep_alive_interval = None

    async def _async_keep_alive(self, _now: datetime) -> None:
        """Rewrite the charging current setpoint to reset the EMS timeout."""
        current = self.ems_control.charging_current
        if not self.ems_control.is_enabled or current is None:
            return
        try:
            await self.ems_control.write("charging_current", current)
        except ModbusError as err:
            if not self._keep_alive_failed:
                _LOGGER.warning("EMS keep-alive write failed: %s", err)
            self._keep_alive_failed = True
            return
        if self._keep_alive_failed:
            _LOGGER.info("EMS keep-alive write succeeded again")
        self._keep_alive_failed = False


@dataclass(slots=True)
class WallboxData:
    """Decoded identity, optional meter, EVSE and EMS control register components."""

    identity: WallboxIdentity
    meter: WallboxMeter
    session_energy: WallboxSessionEnergy
    evse: WallboxEVSE
    ems_control: WallboxEMSControl


@dataclass(slots=True)
class WallboxRuntimeData:
    """Runtime objects owned by a config entry."""

    coordinator: KathreinCoordinator


type KathreinConfigEntry = ConfigEntry[WallboxRuntimeData]
