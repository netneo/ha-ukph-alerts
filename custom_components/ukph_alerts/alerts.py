"""Built-in phone alerts and the ukph_alerts_new_warning event.

Each warning/river gets a key and a rank. A notification goes out when something new reaches the
user's chosen level, or an already-notified one gets worse; an optional all-clear when it drops away.
What has been seen/notified is persisted, so a restart doesn't re-send anything.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALERT_GRID,
    CONF_ALERT_HEALTH,
    CONF_ALERT_POWER,
    CONF_ALERT_THREAT,
    DEFAULT_ALERT_GRID,
    DEFAULT_ALERT_HEALTH,
    DEFAULT_ALERT_POWER,
    DEFAULT_ALERT_THREAT,
    POWER_ALERT_NEAR_KM,
    THREAT_LEVELS,
    CONF_ALL_CLEAR,
    CONF_MIN_FLOOD,
    CONF_MIN_MET,
    CONF_NOTIFY,
    CONF_RIVER_ALERT,
    DEFAULT_ALL_CLEAR,
    DEFAULT_MIN_FLOOD,
    DEFAULT_MIN_MET,
    DEFAULT_RIVER_ALERT,
    DOMAIN,
    EVENT_NEW_WARNING,
    LOGGER,
    PANEL_URL_PATH,
)
from .coordinator import UkphConfigEntry, UkphCoordinator

MET_RANK = {"yellow": 1, "amber": 2, "red": 3}
FLOOD_RANK = {"flood_alert": 1, "flood_warning": 2, "severe_flood_warning": 3}
RIVER_RANK = {"high": 1, "very_high": 2}
RIVER_MIN = {"high": 1, "very_high": 2, "very_high_rising": 2}
GRID_RANK = {"margin_notice": 1, "high_risk": 2, "demand_control": 3}
HEALTH_RANK = {"yellow": 1, "amber": 2, "red": 3}
BATCH_LIMIT = 3  # more new alerts than this in one go are rolled into one summary per type
PANEL_LINK = f"/{PANEL_URL_PATH}"


def _when(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    return dt_util.as_local(value).strftime("%a %d %b %H:%M") if value else ""


class UkphAlerter:
    def __init__(self, hass: HomeAssistant, entry: UkphConfigEntry, options: dict[str, Any]) -> None:
        self.hass = hass
        self.entry = entry
        self.notify: list[str] = options.get(CONF_NOTIFY) or []
        self.min_met = MET_RANK[options.get(CONF_MIN_MET, DEFAULT_MIN_MET)]
        self.min_flood = FLOOD_RANK[options.get(CONF_MIN_FLOOD, DEFAULT_MIN_FLOOD)]
        self.river_mode = options.get(CONF_RIVER_ALERT, DEFAULT_RIVER_ALERT)
        self.all_clear = options.get(CONF_ALL_CLEAR, DEFAULT_ALL_CLEAR)
        self.power_mode = options.get(CONF_ALERT_POWER, DEFAULT_ALERT_POWER)
        self.health_min = options.get(CONF_ALERT_HEALTH, DEFAULT_ALERT_HEALTH)
        self.threat_on = options.get(CONF_ALERT_THREAT, DEFAULT_ALERT_THREAT)
        self.grid_min = options.get(CONF_ALERT_GRID, DEFAULT_ALERT_GRID)
        self.radius = options.get("flood_radius_km", 10)
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.alerts")
        self._state: dict[str, dict[str, Any]] = {"seen": {}, "notified": {}}

    async def async_start(self) -> None:
        if loaded := await self._store.async_load():
            self._state = loaded
        data = self.entry.runtime_data
        for coordinator in (data.met_office, data.floods, data.rivers, data.power, data.health, data.grid,
                            data.threat):
            self.entry.async_on_unload(coordinator.async_add_listener(self._schedule))
        await self._evaluate()

    @callback
    def _schedule(self) -> None:
        self.entry.async_create_background_task(self.hass, self._evaluate(), f"{DOMAIN} alerts")

    # --- current items per source -------------------------------------------------------------

    def _items(self, kind: str, coordinator: UkphCoordinator) -> tuple[list[dict[str, Any]], bool] | None:
        """(items, complete), or None if the source failed last time, so its warnings aren't mistaken for cleared.

        Each item is built on its own: one malformed record is logged and skipped rather than taking the
        other alerts down with it. complete is False when anything was skipped.
        """
        if not coordinator.last_update_success or coordinator.data is None:
            return None
        build, source = {
            "met": (self._met_item, lambda d: d),
            "flood": (self._flood_item, lambda d: d),
            "power": (self._power_item, lambda d: [c for c in d if not c.get("planned")]),
            "health": (self._health_item,
                       lambda d: [(k, h) for k, h in d.items() if h and h.get("level") in HEALTH_RANK]),
            "grid": (self._grid_item, lambda d: [n for n in d.get("active", []) if n.get("status") in GRID_RANK]),
            "river": (self._river_item,
                      lambda d: [s for s in d.get("stations", []) if s.get("status") in RIVER_RANK]),
        }[kind]
        items, complete = [], True
        for record in source(coordinator.data):
            try:
                items.append(build(record))
            except (KeyError, TypeError, ValueError, AttributeError, IndexError) as err:
                complete = False
                LOGGER.warning("Skipping a %s alert that couldn't be read (%r): %r", kind, err, record)
        return items, complete

    @staticmethod
    def _met_item(w: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": f"met:{w.get('id') or w.get('title')}",
            "rank": MET_RANK.get(w.get("level") or "", 0),
            "level": w.get("level"),
            "title": f"⚠️ {(w.get('level') or 'Weather').capitalize()} warning: {w.get('hazard') or w.get('title')}",
            "message": " · ".join(filter(None, [
                f"{_when(w.get('valid_from'))} to {_when(w.get('valid_to'))}" if w.get("valid_from") else "",
                ", ".join(w.get("areas") or []),
            ])) or (w.get("summary") or ""),
            "link": w.get("link") or PANEL_LINK,
            "clear": f"Met Office {w.get('level') or ''} warning for {w.get('hazard') or 'weather'} has ended.",
        }

    @staticmethod
    def _flood_item(w: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": f"flood:{w.get('id')}",
            "rank": FLOOD_RANK.get(w["severity"], 0),
            "level": w["severity"],
            "title": f"🌊 {w['severity'].replace('_', ' ').capitalize()}: {w.get('description')}",
            "message": (w.get("message") or w.get("river_or_sea") or "")[:300],
            "link": w.get("link") or PANEL_LINK,
            "clear": f"{w['severity'].replace('_', ' ').capitalize()} for {w.get('description')} is no longer in force.",
        }

    @staticmethod
    def _power_item(c: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": f"power:{c['id']}",
            "rank": 1,
            "level": "power_cut",
            "distance": c["distance_km"],
            "title": f"🔌 Power cut {c['distance_km']} km away",
            "message": " · ".join(filter(None, [
                f"{c['customers']} customers off" if c.get("customers") else "",
                f"{c['network']}",
                f"estimated back {_when(c['estimated_restore'])}" if c.get("estimated_restore") else "",
                (c.get("cause") or "")[:160],
            ])),
            "link": c.get("link") or PANEL_LINK,
            "clear": f"The power cut {c['distance_km']} km away is no longer listed by {c['network']}.",
        }

    @staticmethod
    def _health_item(kh: tuple[str, dict[str, Any]]) -> dict[str, Any]:
        k, h = kh
        return {
            "key": f"health:{k}:{h['region']}",  # must start "health:" so the all-clear sweep finds it
            "rank": HEALTH_RANK[h["level"]],
            "level": h["level"],
            "title": f"{'🥵' if k == 'heat' else '🥶'} {h['level'].capitalize()} {k}-health alert: {h['region']}",
            "message": (h.get("summary") or "")[:300],
            "link": h.get("link") or PANEL_LINK,
            "clear": f"The {k}-health alert for {h['region']} has ended.",
        }

    @staticmethod
    def _grid_item(n: dict[str, Any]) -> dict[str, Any]:
        return {
            "key": f"grid:{n['type']}:{n['start'].isoformat() if hasattr(n['start'], 'isoformat') else n['start']}",
            "rank": GRID_RANK[n["status"]],
            "level": n["status"],
            "title": f"⚡ Grid notice: {n['type']}",
            "message": n["summary"] + ". NESO uses these to get more power onto the grid; it doesn't by itself "
                       "mean power cuts are expected.",
            "link": PANEL_LINK,
            "clear": f"{n['summary']}: ended or cancelled.",
        }

    @staticmethod
    def _river_item(s: dict[str, Any]) -> dict[str, Any]:
        state = "very high" if s["status"] == "very_high" else "high"
        # SEPA stations only give a state: no level in metres, typical range or trend.
        parts = []
        if s.get("level") is not None:
            parts.append(f"{s['level']:.2f} m, {s.get('trend') or 'trend unknown'}.")
        if s.get("typical_low") is not None and s.get("typical_high") is not None:
            parts.append(f"Normal range {s['typical_low']:.2f}–{s['typical_high']:.2f} m.")
        return {
            "key": f"river:{s['ref']}",
            "rank": RIVER_RANK[s["status"]],
            "level": s["status"],
            "rising": s.get("trend") == "rising",
            "title": f"🏞️ {s['river']} at {s['station']}: {state}",
            "message": " ".join(parts) or f"{s['river']} at {s['station']}: {state}"
                                           + (f" ({s['source']})." if s.get("source") else "."),
            "link": s.get("link") or PANEL_LINK,
            "clear": f"{s['river']} at {s['station']} is back below its alert level.",
        }

    def _meets(self, kind: str, item: dict[str, Any], already_notified: bool) -> bool:
        if kind == "met":
            return item["rank"] >= self.min_met
        if kind == "flood":
            return item["rank"] >= self.min_flood
        if kind == "power":
            return self.power_mode != "off" and item["distance"] <= (
                POWER_ALERT_NEAR_KM if self.power_mode == "near" else self.radius)
        if kind == "health":
            return self.health_min != "off" and item["rank"] >= HEALTH_RANK[self.health_min]
        if kind == "grid":
            return self.grid_min != "off" and item["rank"] >= GRID_RANK[self.grid_min]
        if self.river_mode == "off":
            return False
        if item["rank"] < RIVER_MIN[self.river_mode]:
            return False
        # "Rising" is only needed to start an alert, not to keep it active.
        return already_notified or self.river_mode != "very_high_rising" or item["rising"]

    # --- evaluation ---------------------------------------------------------------------------

    def _diff(self, kind: str, coordinator: UkphCoordinator, outgoing: dict[str, list[dict[str, Any]]],
              clears: list[dict[str, Any]]) -> bool:
        """Compare one source with what was seen/notified; queue sends and clears. True if state changed."""
        seen, notified = self._state["seen"], self._state["notified"]
        changed = False
        result = self._items(kind, coordinator)
        if result is None:
            return False
        items, complete = result
        current = {i["key"]: i for i in items}
        for key, item in current.items():
            before = seen.get(key)
            if before is None or item["rank"] > before["rank"]:
                self.hass.bus.async_fire(EVENT_NEW_WARNING, {
                    "type": {"met": "met_office", "flood": "flood", "river": "river", "power": "power_cut",
                             "health": "health", "grid": "grid"}[kind],
                    "change": "new" if before is None else "upgrade",
                    "level": item["level"], "title": item["title"], "link": item["link"],
                })
            if before is None or before["rank"] != item["rank"]:
                seen[key] = {"rank": item["rank"], "clear": item["clear"]}
                changed = True
            was = notified.get(key)
            if self._meets(kind, item, was is not None):
                if was is None or item["rank"] > was["rank"]:
                    outgoing.setdefault(kind, []).append(item)
                    notified[key] = {"rank": item["rank"], "clear": item["clear"]}
                    changed = True
            elif was is not None:
                clears.append({"key": key, "message": item["clear"]})
                del notified[key]
                changed = True
        if not complete:
            return changed
        for key in [k for k in seen if k.startswith(f"{kind}:") and k not in current]:
            if key in notified:
                clears.append({"key": key, "message": notified.pop(key)["clear"]})
            del seen[key]
            changed = True
        return changed

    async def _evaluate(self) -> None:
        data = self.entry.runtime_data
        outgoing: dict[str, list[dict[str, Any]]] = {}
        clears: list[dict[str, Any]] = []
        changed = False

        try:
            await self._threat(data.threat)
        except Exception:  # noqa: BLE001 - never let one source stop the others
            LOGGER.exception("Threat-level alert check failed")
        for kind, coordinator in (("met", data.met_office), ("flood", data.floods), ("river", data.rivers),
                                  ("power", data.power), ("health", data.health), ("grid", data.grid)):
            try:
                changed |= self._diff(kind, coordinator, outgoing, clears)
            except Exception:  # noqa: BLE001 - never let one source stop the others
                LOGGER.exception("%s alert check failed", kind)
                changed = True  # it may have updated some state before failing

        for kind, items in outgoing.items():
            if len(items) > BATCH_LIMIT:
                names = {"met": "Met Office warnings", "flood": "flood warnings", "river": "rivers running high",
                         "power": "power cuts", "health": "health alerts", "grid": "grid notices"}
                await self._send(f"{len(items)} new {names[kind]} near you",
                                 "; ".join(i["title"] for i in items)[:400], PANEL_LINK, f"ukph-{kind}-batch")
            else:
                for i in items:
                    await self._send(i["title"], i["message"], i["link"], i["key"])
        if self.all_clear:
            for c in clears:
                await self._send("✅ All clear", c["message"], PANEL_LINK, c["key"])
        if changed:
            await self._store.async_save(self._state)

    async def _threat(self, coordinator: UkphCoordinator) -> None:
        """The threat level is a single value: alert whenever it changes, up or down."""
        if not coordinator.last_update_success or not coordinator.data:
            return
        level = coordinator.data["level"]
        before = self._state["seen"].get("threat:national")
        if before == level:
            return
        self._state["seen"]["threat:national"] = level
        await self._store.async_save(self._state)
        if before is None:
            return  # first run: just remember it, nothing has changed
        raised = THREAT_LEVELS.index(level) > THREAT_LEVELS.index(before)
        self.hass.bus.async_fire(EVENT_NEW_WARNING, {"type": "threat_level", "change": "upgrade" if raised else "downgrade",
                                                     "level": level, "title": f"UK threat level now {level.upper()}",
                                                     "link": coordinator.data.get("link")})
        if self.threat_on:
            await self._send(f"🛡️ UK terrorism threat level {'raised' if raised else 'lowered'} to {level.upper()}",
                             f"Was {before.upper()}. {coordinator.data.get('summary') or ''}"[:300],
                             coordinator.data.get("link") or PANEL_LINK, "threat")

    async def _send(self, title: str, message: str, link: str, tag: str) -> None:
        tag = "ukph-" + "".join(ch if ch.isalnum() else "-" for ch in tag)[:60]
        payload = {
            "title": title,
            "message": message or title,
            # url = iOS, clickAction = Android; tag replaces the earlier notification for the same warning.
            "data": {"url": link, "clickAction": link, "tag": tag, "group": "ukph-alerts",
                     "channel": "UK Prepper Hub alerts", "ttl": 0, "priority": "high"},
        }
        for service in self.notify:
            if not self.hass.services.has_service("notify", service):
                LOGGER.warning("Alert not sent: notify.%s no longer exists", service)
                continue
            try:
                await self.hass.services.async_call("notify", service, payload, blocking=True)
            except Exception as err:  # noqa: BLE001 - a broken phone mustn't stop the other alerts
                LOGGER.warning("Alert to notify.%s failed: %s", service, err)
