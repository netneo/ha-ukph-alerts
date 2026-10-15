"""UK Prepper Hub Alerts: Met Office warnings, EA flood warnings and UKPH daily news."""

from __future__ import annotations

import asyncio

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import UkphApi
from .const import (
    CONF_RADIUS,
    CONF_REGION,
    DEFAULT_RADIUS,
    INTERVAL_FLOODS,
    INTERVAL_MET_OFFICE,
    INTERVAL_NEWS,
)
from .coordinator import UkphConfigEntry, UkphCoordinator, UkphData

PLATFORMS = [Platform.SENSOR]


def _option(entry: UkphConfigEntry, key: str, default=None):
    """Options (set via Configure) override the values from the initial setup."""
    return entry.options.get(key, entry.data.get(key, default))


async def async_setup_entry(hass: HomeAssistant, entry: UkphConfigEntry) -> bool:
    api = UkphApi(async_get_clientsession(hass))
    region = _option(entry, CONF_REGION, "UK")
    radius = _option(entry, CONF_RADIUS, DEFAULT_RADIUS)

    async def fetch_floods():
        # Read HA's home location on every poll, so a corrected location is picked up without reconfiguring.
        return await api.floods(hass.config.latitude, hass.config.longitude, radius)

    data = UkphData(
        met_office=UkphCoordinator(hass, entry, "met_office", INTERVAL_MET_OFFICE,
                                   lambda: api.met_office(region)),
        floods=UkphCoordinator(hass, entry, "floods", INTERVAL_FLOODS, fetch_floods),
        news=UkphCoordinator(hass, entry, "news", INTERVAL_NEWS, api.news),
    )
    # Plain refresh, not first_refresh: a source that is down just leaves its own sensors unavailable.
    await asyncio.gather(data.met_office.async_refresh(), data.floods.async_refresh(),
                         data.news.async_refresh())
    entry.runtime_data = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: UkphConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: UkphConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
