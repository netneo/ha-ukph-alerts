"""Sensors for Met Office warnings, EA flood warnings and UKPH daily news."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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

HIGH_STATUSES = ("high", "very_high")
from .coordinator import UkphConfigEntry, UkphCoordinator


def _highest_met_office(warnings: list[dict]) -> str:
    return max((w["level"] or "none" for w in warnings), key=MET_OFFICE_LEVELS.index, default="none")


def _rivers_high(data: dict | None) -> list[dict]:
    return [s for s in (data or {}).get("stations", []) if s.get("status") in HIGH_STATUSES]


def _device_info(entry: UkphConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=NAME,
        manufacturer="UK Prepper Hub",
        entry_type=DeviceEntryType.SERVICE,
        sw_version=VERSION,
        configuration_url="https://ukprepperhub.co.uk/",
    )


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
        key="rivers_above_normal",
        translation_key="rivers_above_normal",
        icon="mdi:waves",
        source="rivers",
        attribution=ATTRIBUTION_EA,
        value_fn=lambda data: len(_rivers_high(data)) if data else None,
        attrs_fn=lambda data, entry: {
            "radius_km": _opt(entry, CONF_RADIUS),
            "rivers_above_normal": [
                {k: s[k] for k in ("river", "station", "level", "status", "trend", "link")}
                for s in _rivers_high(data)
            ],
            "stations_shown": len(data["stations"]),
            "stations_in_radius": data["total_usable"],
            "stations": data["stations"],
        } if data else {},
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

    # One sensor per river station. The station list is rebuilt daily, so add any new ones as they appear.
    rivers = entry.runtime_data.rivers
    known: set[str] = set()

    @callback
    def add_new_stations() -> None:
        new = [s for s in (rivers.data or {}).get("stations", []) if s["ref"] not in known]
        known.update(s["ref"] for s in new)
        if new:
            async_add_entities(RiverStationSensor(rivers, entry, s) for s in new)

    add_new_stations()
    entry.async_on_unload(rivers.async_add_listener(add_new_stations))

    # Tidy away sensors for stations no longer in range (radius changed, station closed). Only when the
    # station list actually loaded, so a temporary EA outage never deletes anything.
    if rivers.last_update_success and rivers.data is not None:
        prefix = f"{entry.entry_id}_river_"
        registry = er.async_get(hass)
        for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
            if reg.unique_id.startswith(prefix) and reg.unique_id[len(prefix):] not in known:
                registry.async_remove(reg.entity_id)


class UkphSensor(CoordinatorEntity[UkphCoordinator], SensorEntity):
    """One sensor, driven by its source's coordinator."""

    _attr_has_entity_name = True
    # The long text and story list would bloat the recorder database every day.
    _unrecorded_attributes = frozenset({"brief", "stories", "warnings", "stations", "rivers_above_normal"})
    entity_description: UkphSensorDescription

    def __init__(
        self, coordinator: UkphCoordinator, entry: UkphConfigEntry, description: UkphSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_attribution = description.attribution
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return self.entity_description.attrs_fn(self.coordinator.data, self._entry)


class RiverStationSensor(CoordinatorEntity[UkphCoordinator], SensorEntity):
    """Water level at one EA monitoring station."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:waves-arrow-up"
    _attr_native_unit_of_measurement = UnitOfLength.METERS
    _attr_device_class = SensorDeviceClass.DISTANCE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_attribution = ATTRIBUTION_EA

    def __init__(self, coordinator: UkphCoordinator, entry: UkphConfigEntry, station: dict) -> None:
        super().__init__(coordinator)
        self._ref = station["ref"]
        self._attr_unique_id = f"{entry.entry_id}_river_{self._ref}"
        self._attr_name = f"River level {station['river']} at {station['station']}"
        self._attr_device_info = _device_info(entry)

    @property
    def _station(self) -> dict | None:
        return next((s for s in (self.coordinator.data or {}).get("stations", []) if s["ref"] == self._ref), None)

    @property
    def available(self) -> bool:
        s = self._station
        return super().available and s is not None and s.get("level") is not None

    @property
    def native_value(self) -> float | None:
        s = self._station
        return s["level"] if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._station or {}
        return {k: s.get(k) for k in (
            "river", "station", "status", "trend", "change_1h_m", "typical_low", "typical_high",
            "highest_recent", "max_on_record", "distance_km", "reading_time", "link")}
