"""Update coordinators: one per source, so one failing source doesn't take the others down."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiError
from .const import DOMAIN, LOGGER


class UkphCoordinator(DataUpdateCoordinator[Any]):
    """Polls a single source."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        source: str,
        interval: timedelta,
        fetch: Callable[[], Awaitable[Any]],
    ) -> None:
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {source}",
            update_interval=interval,
        )
        self._fetch = fetch

    async def _async_update_data(self) -> Any:
        try:
            return await self._fetch()
        except ApiError as err:
            raise UpdateFailed(str(err)) from err


@dataclass
class UkphData:
    """Runtime data stored on the config entry."""

    met_office: UkphCoordinator
    floods: UkphCoordinator
    news: UkphCoordinator


type UkphConfigEntry = ConfigEntry[UkphData]
