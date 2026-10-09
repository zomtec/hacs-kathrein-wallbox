"""Polling coordinator for Kathrein Wallbox register data."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from modbus_connection import ModbusError, ModbusUnit

from .const import DEFAULT_SCAN_INTERVAL
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
        entry: ConfigEntry,
        unit: ModbusUnit,
        update_interval: timedelta | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Kathrein Wallbox",
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
            raise UpdateFailed(f"Unable to read Kathrein Wallbox: {err}") from err

        try:
            await self.meter.async_update()
        except ModbusError as err:
            if self.meter_available:
                _LOGGER.warning("Energy meter registers are no longer available: %s", err)
            self.meter_available = False
            self.session_energy_available = False
        else:
            self.meter_available = self.meter.has_plausible_reference
            if self.meter_available:
                try:
                    await self.session_energy.async_update()
                except ModbusError as err:
                    if self.session_energy_available:
                        _LOGGER.warning("Session energy register is no longer available: %s", err)
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