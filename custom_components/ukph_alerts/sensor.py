"""Sensors for Met Office warnings, EA flood warnings and UKPH daily news."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTRIBUTION_EA,
    ATTRIBUTION_MET_OFFICE,
    ATTRIBUTION_UKPH,
    CONF_RADIUS,
    CONF_REGION,
    DOMAIN,
    FLOOD_LEVELS,
    MET_OFFICE_LEVELS,
    MET_OFFICE_REGIONS,
    NAME,
    VERSION,
)
from .coordinator import UkphConfigEntry, UkphCoordinator


def _highest_met_office(warnings: list[dict]) -> str:
    return max((w["level"] or "none" for w in warnings), key=MET_OFFICE_LEVELS.index, default="none")


def _highest_flood(warnings: list[dict]) -> str:
    return max((w["severity"] for w in warnings), key=FLOOD_LEVELS.index, default="none")


@dataclass(frozen=True, kw_only=True)
class UkphSensorDescription(SensorEntityDescription):
    source: str
    attribution: str
    value_fn: Callable[[Any], Any]
    attrs_fn: Callable[[Any, UkphConfigEntry], dict[str, Any]] = lambda data, entry: {}


SENSORS: tuple[UkphSensorDescription, ...] = (
    UkphSensorDescription(
        key="met_office_warnings",
        translation_key="met_office_warnings",
        icon="mdi:weather-lightning-rainy",
        source="met_office",
        attribution=ATTRIBUTION_MET_OFFICE,
        value_fn=len,
        attrs_fn=lambda data, entry: {
            "region": MET_OFFICE_REGIONS.get(_opt(entry, CONF_REGION)),
            "highest_level": _highest_met_office(data),
            "warnings": data,
        },
    ),
    UkphSensorDescription(
        key="met_office_highest_level",
        translation_key="met_office_highest_level",
        icon="mdi:alert",
        device_class=SensorDeviceClass.ENUM,
        options=MET_OFFICE_LEVELS,
        source="met_office",
        attribution=ATTRIBUTION_MET_OFFICE,
        value_fn=_highest_met_office,
    ),
    UkphSensorDescription(
        key="flood_warnings",
        translation_key="flood_warnings",
        icon="mdi:home-flood",
        source="floods",
        attribution=ATTRIBUTION_EA,
        value_fn=len,
        attrs_fn=lambda data, entry: {
            "radius_km": _opt(entry, CONF_RADIUS),
            "highest_severity": _highest_flood(data),
            "warnings": data,
        },
    ),
    UkphSensorDescription(
        key="flood_highest_severity",
        translation_key="flood_highest_severity",
        icon="mdi:waves-arrow-up",
        device_class=SensorDeviceClass.ENUM,
        options=FLOOD_LEVELS,
        source="floods",
        attribution=ATTRIBUTION_EA,
        value_fn=_highest_flood,
    ),
    UkphSensorDescription(
        key="daily_news",
        translation_key="daily_news",
        icon="mdi:newspaper-variant-outline",
        source="news",
        attribution=ATTRIBUTION_UKPH,
        value_fn=lambda data: data["title"][:255] if data else None,
        attrs_fn=lambda data, entry: {
            "link": data["link"],
            "published": data["published"],
            "brief": data["brief"],
            "story_count": len(data["stories"]),
            "stories": data["stories"],
            "schema_version": data["schema_version"],
        } if data else {},
    ),
)


def _opt(entry: UkphConfigEntry, key: str) -> Any:
    return entry.options.get(key, entry.data.get(key))


async def async_setup_entry(
    hass: HomeAssistant, entry: UkphConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities(
        UkphSensor(getattr(entry.runtime_data, d.source), entry, d) for d in SENSORS
    )


class UkphSensor(CoordinatorEntity[UkphCoordinator], SensorEntity):
    """One sensor, driven by its source's coordinator."""

    _attr_has_entity_name = True
    # The long text and story list would bloat the recorder database every day.
    _unrecorded_attributes = frozenset({"brief", "stories", "warnings"})
    entity_description: UkphSensorDescription

    def __init__(
        self, coordinator: UkphCoordinator, entry: UkphConfigEntry, description: UkphSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_attribution = description.attribution
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="UK Prepper Hub",
            entry_type=DeviceEntryType.SERVICE,
            sw_version=VERSION,
            configuration_url="https://ukprepperhub.co.uk/",
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data, self._entry)
