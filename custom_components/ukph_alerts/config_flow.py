"""Setup and Configure screens."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
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
    DEFAULT_RADIUS,
    DOMAIN,
    MAX_RADIUS,
    MET_OFFICE_REGIONS,
    MIN_RADIUS,
    NAME,
)


def _schema(region: str | None, radius: float) -> vol.Schema:
    region_key = (
        vol.Required(CONF_REGION, default=region) if region else vol.Required(CONF_REGION)
    )
    return vol.Schema(
        {
            region_key: SelectSelector(
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
        return self.async_show_form(step_id="user", data_schema=_schema(None, DEFAULT_RADIUS))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return UkphOptionsFlow()


class UkphOptionsFlow(OptionsFlow):
    """The Configure button: change region or radius without removing the integration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_schema(current.get(CONF_REGION), current.get(CONF_RADIUS, DEFAULT_RADIUS)),
        )
