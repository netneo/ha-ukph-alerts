"""Setup and Configure screens."""

from __future__ import annotations

from math import cos, radians
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from homeassistant.util import slugify

from .const import (
    CONF_ALL_CLEAR,
    CONF_MIN_FLOOD,
    CONF_MIN_MET,
    CONF_NOTIFY,
    CONF_RADIUS,
    CONF_REGION,
    CONF_RIVER_ALERT,
    CONF_SIDEBAR,
    DEFAULT_ALL_CLEAR,
    DEFAULT_MIN_FLOOD,
    DEFAULT_MIN_MET,
    DEFAULT_RADIUS,
    DEFAULT_RIVER_ALERT,
    DOMAIN,
    MAX_RADIUS,
    MET_OFFICE_REGION_POINTS,
    MET_OFFICE_REGIONS,
    MIN_RADIUS,
    NAME,
)


def guess_region(lat: float | None, lon: float | None) -> str:
    """Region of the nearest reference point to HA's home location; whole UK if it's outside the UK.

    Only a starting suggestion for the dropdown, so near a regional border it can be wrong.
    """
    if lat is None or lon is None or not (49.8 <= lat <= 61.0 and -8.7 <= lon <= 2.0):
        return "UK"
    k = cos(radians(lat))
    return min(
        ((region, p) for region, points in MET_OFFICE_REGION_POINTS.items() for p in points),
        key=lambda rp: (rp[1][0] - lat) ** 2 + ((rp[1][1] - lon) * k) ** 2,
    )[0]


MET_LEVELS = [("yellow", "Yellow, amber and red"), ("amber", "Amber and red"), ("red", "Red only")]
FLOOD_LEVELS = [("flood_alert", "Flood alerts and above"), ("flood_warning", "Flood warnings and severe"),
                ("severe_flood_warning", "Severe flood warnings only")]
RIVER_LEVELS = [("off", "Off"), ("high", "Above its normal range"), ("very_high", "Above its highest recent level"),
                ("very_high_rising", "Above its highest recent level and still rising")]


def phone_services(hass: HomeAssistant) -> list[SelectOptionDict]:
    """The Home Assistant app's notify services, labelled with the phone's own name where we can find it."""
    services = sorted(s for s in hass.services.async_services().get("notify", {}) if s.startswith("mobile_app_"))
    names = {
        f"mobile_app_{slugify(d.name_by_user or d.name or '')}": d.name_by_user or d.name
        for d in dr.async_get(hass).devices.values()
        if any(i[0] == "mobile_app" for i in d.identifiers)
    }
    return [SelectOptionDict(value=s, label=names.get(s) or s.removeprefix("mobile_app_").replace("_", " ").title())
            for s in services]


def _select(options: list[tuple[str, str]]) -> SelectSelector:
    return SelectSelector(SelectSelectorConfig(
        options=[SelectOptionDict(value=v, label=l) for v, l in options], mode=SelectSelectorMode.DROPDOWN))


def _schema(hass: HomeAssistant, current: dict[str, Any]) -> vol.Schema:
    phones = phone_services(hass)
    fields: dict[Any, Any] = {
        vol.Required(CONF_REGION, default=current[CONF_REGION]): SelectSelector(
            SelectSelectorConfig(
                options=[SelectOptionDict(value=k, label=v) for k, v in MET_OFFICE_REGIONS.items()],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(CONF_RADIUS, default=current[CONF_RADIUS]): NumberSelector(
            NumberSelectorConfig(
                min=MIN_RADIUS, max=MAX_RADIUS, step=1,
                unit_of_measurement="km", mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(CONF_SIDEBAR, default=current[CONF_SIDEBAR]): BooleanSelector(),
    }
    if phones:
        valid = {p["value"] for p in phones}
        fields[vol.Optional(CONF_NOTIFY, default=[p for p in current[CONF_NOTIFY] if p in valid])] = SelectSelector(
            SelectSelectorConfig(options=phones, multiple=True, mode=SelectSelectorMode.LIST))
    fields[vol.Required(CONF_MIN_MET, default=current[CONF_MIN_MET])] = _select(MET_LEVELS)
    fields[vol.Required(CONF_MIN_FLOOD, default=current[CONF_MIN_FLOOD])] = _select(FLOOD_LEVELS)
    fields[vol.Required(CONF_RIVER_ALERT, default=current[CONF_RIVER_ALERT])] = _select(RIVER_LEVELS)
    fields[vol.Required(CONF_ALL_CLEAR, default=current[CONF_ALL_CLEAR])] = BooleanSelector()
    return vol.Schema(fields)


def _defaults(hass: HomeAssistant, existing: dict[str, Any] | None) -> dict[str, Any]:
    existing = existing or {}
    return {
        CONF_REGION: existing.get(CONF_REGION) or guess_region(hass.config.latitude, hass.config.longitude),
        CONF_RADIUS: existing.get(CONF_RADIUS, DEFAULT_RADIUS),
        CONF_SIDEBAR: existing.get(CONF_SIDEBAR, True),
        # New installs: every phone pre-ticked (least friction). Existing installs keep what they chose,
        # and an upgrade from before alerts existed starts with none rather than surprising anyone.
        CONF_NOTIFY: existing.get(CONF_NOTIFY, [] if existing else [p["value"] for p in phone_services(hass)]),
        CONF_MIN_MET: existing.get(CONF_MIN_MET, DEFAULT_MIN_MET),
        CONF_MIN_FLOOD: existing.get(CONF_MIN_FLOOD, DEFAULT_MIN_FLOOD),
        CONF_RIVER_ALERT: existing.get(CONF_RIVER_ALERT, DEFAULT_RIVER_ALERT),
        CONF_ALL_CLEAR: existing.get(CONF_ALL_CLEAR, DEFAULT_ALL_CLEAR),
    }


class UkphConfigFlow(ConfigFlow, domain=DOMAIN):
    """First-time setup. One instance per Home Assistant install."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            # An empty multi-select is left out of user_input entirely, so "no phones" must be explicit.
            return self.async_create_entry(title=NAME, data={CONF_NOTIFY: [], **user_input})
        defaults = _defaults(self.hass, None)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(self.hass, defaults),
            description_placeholders={"region": MET_OFFICE_REGIONS[defaults[CONF_REGION]]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UkphOptionsFlow()


class UkphOptionsFlow(OptionsFlow):
    """The Configure button: change settings without removing the integration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # Same as setup: unticking every phone must not fall back to the phones chosen at setup.
            return self.async_create_entry(data={CONF_NOTIFY: [], **user_input})
        current = _defaults(self.hass, {**self.config_entry.data, **self.config_entry.options})
        return self.async_show_form(step_id="init", data_schema=_schema(self.hass, current))
