"""On/off alert sensors: the easy thing to trigger automations from."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION_EA, ATTRIBUTION_MET_OFFICE
from .coordinator import UkphConfigEntry, UkphCoordinator
from .sensor import _device_info, _rivers_high


@dataclass(frozen=True, kw_only=True)
class UkphBinaryDescription(BinarySensorEntityDescription):
    source: str
    attribution: str
    items_fn: Callable[[Any], list[dict]]
    summary_fn: Callable[[dict], str]


BINARY_SENSORS: tuple[UkphBinaryDescription, ...] = (
    UkphBinaryDescription(
        key="weather_warning_active",
        translation_key="weather_warning_active",
        icon="mdi:weather-lightning-rainy",
        source="met_office",
        attribution=ATTRIBUTION_MET_OFFICE,
        items_fn=lambda data: data or [],
        summary_fn=lambda w: f"{(w.get('level') or '').capitalize()} warning: {w.get('hazard') or w.get('title')}",
    ),
    UkphBinaryDescription(
        key="flood_warning_nearby",
        translation_key="flood_warning_nearby",
        icon="mdi:home-flood",
        source="floods",
        attribution=ATTRIBUTION_EA,
        items_fn=lambda data: data or [],
        summary_fn=lambda w: f"{w['severity'].replace('_', ' ').capitalize()}: {w.get('description')}",
    ),
    UkphBinaryDescription(
        key="river_high_nearby",
        translation_key="river_high_nearby",
        icon="mdi:waves-arrow-up",
        source="rivers",
        attribution=ATTRIBUTION_EA,
        items_fn=_rivers_high,
        summary_fn=lambda s: f"{s['river']} at {s['station']}: {s['status'].replace('_', ' ')}"
        + (f", {s['trend']}" if s.get("trend") else ""),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: UkphConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        UkphBinarySensor(getattr(entry.runtime_data, d.source), entry, d) for d in BINARY_SENSORS
    )


class UkphBinarySensor(CoordinatorEntity[UkphCoordinator], BinarySensorEntity):
    """On while anything of this kind is in force."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.SAFETY  # on = unsafe
    entity_description: UkphBinaryDescription

    def __init__(self, coordinator: UkphCoordinator, entry: UkphConfigEntry, description: UkphBinaryDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_attribution = description.attribution
        self._attr_device_info = _device_info(entry)

    @property
    def _items(self) -> list[dict]:
        return self.entity_description.items_fn(self.coordinator.data)

    @property
    def is_on(self) -> bool:
        return bool(self._items)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"count": len(self._items), "details": [self.entity_description.summary_fn(i) for i in self._items]}
