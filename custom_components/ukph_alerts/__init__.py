"""UK Prepper Hub Alerts: Met Office warnings, EA flood warnings and UKPH daily news."""

from __future__ import annotations

import asyncio

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from .alerts import UkphAlerter
from .api import UkphApi, guess_ukhsa_region
from .config_flow import guess_region
from .const import (
    CONF_RADIUS,
    CONF_REGION,
    CONF_SIDEBAR,
    DEFAULT_RADIUS,
    INTERVAL_FLOODS,
    INTERVAL_MET_OFFICE,
    INTERVAL_NEWS,
    INTERVAL_HEALTH,
    INTERVAL_NATIONAL,
    INTERVAL_POWER,
    INTERVAL_RIVERS,
    POWER_NETWORKS_BY_REGION,
    RIVER_STATION_REFRESH,
)
from .coordinator import UkphConfigEntry, UkphCoordinator, UkphData
from .panel import async_register_panel, async_remove_panel

PLATFORMS = [Platform.SENSOR, Platform.BINARY_SENSOR]


def _option(entry: UkphConfigEntry, key: str, default=None):
    """Options (set via Configure) override the values from the initial setup."""
    return entry.options.get(key, entry.data.get(key, default))


async def async_setup_entry(hass: HomeAssistant, entry: UkphConfigEntry) -> bool:
    api = UkphApi(async_get_clientsession(hass))
    region = _option(entry, CONF_REGION, "UK")
    radius = _option(entry, CONF_RADIUS, DEFAULT_RADIUS)

    # Where home is decides which sources apply: SEPA vs EA as the must-work flood source, which electricity
    # networks to ask, and the UKHSA region. Worked out locally from HA's home location, never sent anywhere.
    home_region = guess_region(hass.config.latitude, hass.config.longitude)
    home = {
        "region": home_region,
        "scotland": home_region in ("os", "he", "gr", "st", "ta", "dg"),
        "networks": POWER_NETWORKS_BY_REGION.get(home_region, []),
        "ukhsa_region": guess_ukhsa_region(hass.config.latitude, hass.config.longitude),
    }

    async def fetch_floods():
        # Read HA's home location on every poll, so a corrected location is picked up without reconfiguring.
        return await api.floods(hass.config.latitude, hass.config.longitude, radius, home["scotland"])

    async def fetch_power():
        return await api.power_cuts(home["networks"], hass.config.latitude, hass.config.longitude, radius)

    async def fetch_health():
        if not home["ukhsa_region"]:
            return {"heat": None, "cold": None}  # UKHSA only covers England
        heat, cold = await asyncio.gather(api.health("heat", home["ukhsa_region"]),
                                          api.health("cold", home["ukhsa_region"]))
        return {"heat": heat, "cold": cold}

    stations: dict = {"list": None, "total": 0, "fetched": None}

    async def fetch_rivers():
        # The station list changes rarely, so rebuild it once a day; readings every poll.
        now = dt_util.utcnow()
        if stations["list"] is None or now - stations["fetched"] > RIVER_STATION_REFRESH:
            stations["list"], stations["total"] = await api.river_stations(
                hass.config.latitude, hass.config.longitude, radius)
            stations["fetched"] = now
        levels = await api.river_levels(stations["list"])
        try:
            sepa = await api.sepa_rivers(hass.config.latitude, hass.config.longitude, radius)
        except Exception:  # noqa: BLE001 - only fatal where SEPA is the home source
            if home["scotland"]:
                raise
            sepa = []
        merged = sorted(levels + sepa, key=lambda s: s["distance_km"])
        return {"stations": merged, "total_usable": stations["total"] + len(sepa)}

    data = UkphData(
        met_office=UkphCoordinator(hass, entry, "met_office", INTERVAL_MET_OFFICE,
                                   lambda: api.met_office(region)),
        floods=UkphCoordinator(hass, entry, "floods", INTERVAL_FLOODS, fetch_floods),
        news=UkphCoordinator(hass, entry, "news", INTERVAL_NEWS, api.news),
        rivers=UkphCoordinator(hass, entry, "rivers", INTERVAL_RIVERS, fetch_rivers),
        threat=UkphCoordinator(hass, entry, "threat", INTERVAL_NATIONAL, api.threat),
        grid=UkphCoordinator(hass, entry, "grid", INTERVAL_NATIONAL, api.grid),
        power=UkphCoordinator(hass, entry, "power", INTERVAL_POWER, fetch_power),
        health=UkphCoordinator(hass, entry, "health", INTERVAL_HEALTH, fetch_health),
        home=home,
    )
    # Plain refresh, not first_refresh: a source that is down just leaves its own sensors unavailable.
    await asyncio.gather(*(c.async_refresh() for c in (
        data.met_office, data.floods, data.news, data.rivers, data.threat, data.grid, data.power, data.health)))
    entry.runtime_data = data

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if _option(entry, CONF_SIDEBAR, True):
        await async_register_panel(hass, entry)
    await UkphAlerter(hass, entry, {**entry.data, **entry.options}).async_start()
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def _async_reload(hass: HomeAssistant, entry: UkphConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: UkphConfigEntry) -> bool:
    async_remove_panel(hass)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
