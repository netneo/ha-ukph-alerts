"""The "UK Prepper Hub" sidebar page."""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    PANEL_COMPONENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    STATIC_URL,
    VERSION,
)
from .coordinator import UkphConfigEntry
from .sensor import SENSORS

FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_register_panel(hass: HomeAssistant, entry: UkphConfigEntry) -> None:
    # Static paths can only be registered once per HA run, so survive reloads.
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("static_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        domain_data["static_registered"] = True

    # Tell the page which entity IDs to read, so it still works if the user renames them.
    registry = er.async_get(hass)
    entities = {
        d.key: registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{d.key}")
        for d in SENSORS
    }

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        module_url=f"{STATIC_URL}/ukph-panel.js?v={VERSION}",
        require_admin=False,
        config={"entities": entities},
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
