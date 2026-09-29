"""
Custom integration to integrate Bermuda BLE Trilateration with Home Assistant.

For more details about this integration, please refer to
https://github.com/agittins/bermuda
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.entity_registry import async_migrate_entries

from .const import _LOGGER, DOMAIN, PLATFORMS, STARTUP_MESSAGE
from .coordinator import BermudaDataUpdateCoordinator
from .util import mac_math_offset, mac_norm

if TYPE_CHECKING:
    from homeassistant.helpers.device_registry import DeviceEntry


@dataclass
class BermudaData:
    """Holds global data for Bermuda."""

    coordinator: BermudaDataUpdateCoordinator


BermudaConfigEntry = ConfigEntry[BermudaData]


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup_entry(hass: HomeAssistant, entry: BermudaConfigEntry) -> bool:
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        _LOGGER.info(STARTUP_MESSAGE)
    coordinator = BermudaDataUpdateCoordinator(hass, entry)
    entry.runtime_data = BermudaData(coordinator)

    async def on_failure():
        _LOGGER.debug("Coordinator last update failed, rasing ConfigEntryNotReady")
        raise ConfigEntryNotReady

    try:
        await coordinator.async_refresh()
    except Exception as ex:  # noqa: BLE001
        _LOGGER.exception(ex)
        await on_failure()
    if not coordinator.last_update_success:
        await on_failure()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: BermudaConfigEntry) -> bool:
    """Migrate previous config entries."""
    _LOGGER.debug("Migrating config from version %s.%s", config_entry.version, config_entry.minor_version)
    _oldversion = f"{config_entry.version}.{config_entry.minor_version}"

    # If config_entry is at version 1, migrate it forward to version 2
    if config_entry.version < 2:
        hass.config_entries.async_update_entry(config_entry, version=2)
        _LOGGER.info("Migrated config entry from version 1 to 2")

    if f"{config_entry.version}.{config_entry.minor_version}" != _oldversion:
        _LOGGER.info("Migrated config entry to version %s.%s", config_entry.version, config_entry.minor_version)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: BermudaConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Implements user-deletion of devices from device registry."""
    coordinator: BermudaDataUpdateCoordinator = config_entry.runtime_data.coordinator
    address = None
    for domain, ident in device_entry.identifiers:
        try:
            if domain == DOMAIN:
                # the identifier should be the base device address, and
                # may have "_range" or some other per-sensor suffix.
                # The address might be a mac address, IRK or iBeacon uuid
                address = ident.split("_")[0]
        except KeyError:
            pass
    if address is not None:
        try:
            coordinator.devices[mac_norm(address)].create_sensor = False
        except KeyError:
            _LOGGER.warning("Failed to locate device entry for %s", address)
        return True
    # Even if we don't know this address it probably just means it's stale or from
    # a previous version that used weirder names. Allow it.
    _LOGGER.warning(
        "Didn't find address for %s but allowing deletion to proceed.",
        device_entry.name,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BermudaConfigEntry) -> bool:
    """Handle removal of an entry."""
    if unload_result := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        _LOGGER.debug("Unloaded platforms.")
    return unload_result


async def async_reload_entry(hass: HomeAssistant, entry: BermudaConfigEntry) -> None:
    """Reload config entry."""
    hass.config_entries.async_schedule_reload(entry.entry_id)
