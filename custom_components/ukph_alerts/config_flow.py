"""Setup and Configure screens."""

from __future__ import annotations

from math import cos, radians
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
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

from .const import (
    CONF_RADIUS,
    CONF_REGION,
    CONF_SIDEBAR,
    DEFAULT_RADIUS,
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


def _schema(region: str, radius: float, sidebar: bool) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_REGION, default=region): SelectSelector(
                SelectSelectorConfig(
                    options=[SelectOptionDict(value=k, label=v) for k, v in MET_OFFICE_REGIONS.items()],
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(CONF_RADIUS, default=radius): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_RADIUS, max=MAX_RADIUS, step=1,
                    unit_of_measurement="km", mode=NumberSelectorMode.BOX,
                )
            ),
            vol.Required(CONF_SIDEBAR, default=sidebar): BooleanSelector(),
        }
    )


class UkphConfigFlow(ConfigFlow, domain=DOMAIN):
    """First-time setup. One instance per Home Assistant install."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=NAME, data=user_input)
        region = guess_region(self.hass.config.latitude, self.hass.config.longitude)
        return self.async_show_form(
            step_id="user",
            data_schema=_schema(region, DEFAULT_RADIUS, True),
            description_placeholders={"region": MET_OFFICE_REGIONS[region]},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UkphOptionsFlow()


class UkphOptionsFlow(OptionsFlow):
    """The Configure button: change settings without removing the integration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(
                current.get(CONF_REGION, "UK"),
                current.get(CONF_RADIUS, DEFAULT_RADIUS),
                current.get(CONF_SIDEBAR, True),
            ),
        )
