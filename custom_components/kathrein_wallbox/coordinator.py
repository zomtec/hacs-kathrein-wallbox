"""Polling coordinator for Kathrein Wallbox register data."""

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from modbus_connection import ModbusError, ModbusUnit

from .const import DEFAULT_SCAN_INTERVAL, DEVICE_NAME, DOMAIN
from .model import (
    WallboxEMSControl,
    WallboxEVSE,
    WallboxIdentity,
    WallboxMeter,
    WallboxSessionEnergy,
)

_LOGGER = logging.getLogger(__name__)


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

    async def _async_update_data(self) -> WallboxData:
        """Read essential registers and isolate the optional energy meter."""
        try:
            await self.identity.async_update()
            await self.evse.async_update()
            await self.ems_control.async_update()
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
        try:
            await self.ems_control.write(field, value)
        except ModbusError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="write_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.async_request_refresh()


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
