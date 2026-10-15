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
        self._store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.alerts")
        self._state: dict[str, dict[str, Any]] = {"seen": {}, "notified": {}}

    async def async_start(self) -> None:
        if loaded := await self._store.async_load():
            self._state = loaded
        data = self.entry.runtime_data
        for coordinator in (data.met_office, data.floods, data.rivers):
            self.entry.async_on_unload(coordinator.async_add_listener(self._schedule))
        await self._evaluate()

    @callback
    def _schedule(self) -> None:
        self.entry.async_create_background_task(self.hass, self._evaluate(), f"{DOMAIN} alerts")

    # --- current items per source -------------------------------------------------------------

    def _items(self, kind: str, coordinator: UkphCoordinator) -> list[dict[str, Any]] | None:
        """None if the source failed last time, so its warnings aren't mistaken for cleared."""
        if not coordinator.last_update_success or coordinator.data is None:
            return None
        if kind == "met":
            return [{
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
            } for w in coordinator.data]
        if kind == "flood":
            return [{
                "key": f"flood:{w.get('id')}",
                "rank": FLOOD_RANK.get(w["severity"], 0),
                "level": w["severity"],
                "title": f"🌊 {w['severity'].replace('_', ' ').capitalize()}: {w.get('description')}",
                "message": (w.get("message") or w.get("river_or_sea") or "")[:300],
                "link": w.get("link") or PANEL_LINK,
                "clear": f"{w['severity'].replace('_', ' ').capitalize()} for {w.get('description')} is no longer in force.",
            } for w in coordinator.data]
        return [{
            "key": f"river:{s['ref']}",
            "rank": RIVER_RANK[s["status"]],
            "level": s["status"],
            "rising": s.get("trend") == "rising",
            "title": f"🏞️ {s['river']} at {s['station']}: {'very high' if s['status'] == 'very_high' else 'high'}",
            "message": f"{s['level']:.2f} m, {s.get('trend') or 'trend unknown'}. Normal range "
                       f"{s['typical_low']:.2f}–{s['typical_high']:.2f} m.",
            "link": s.get("link") or PANEL_LINK,
            "clear": f"{s['river']} at {s['station']} is back below its alert level.",
        } for s in coordinator.data.get("stations", []) if s.get("status") in RIVER_RANK]

    def _meets(self, kind: str, item: dict[str, Any], already_notified: bool) -> bool:
        if kind == "met":
            return item["rank"] >= self.min_met
        if kind == "flood":
            return item["rank"] >= self.min_flood
        if self.river_mode == "off":
            return False
        if item["rank"] < RIVER_MIN[self.river_mode]:
            return False
        # "Rising" is only needed to start an alert, not to keep it active.
        return already_notified or self.river_mode != "very_high_rising" or item["rising"]

    # --- evaluation ---------------------------------------------------------------------------

    async def _evaluate(self) -> None:
        data = self.entry.runtime_data
        seen, notified = self._state["seen"], self._state["notified"]
        outgoing: dict[str, list[dict[str, Any]]] = {}
        clears: list[dict[str, Any]] = []
        changed = False

        for kind, coordinator in (("met", data.met_office), ("flood", data.floods), ("river", data.rivers)):
            items = self._items(kind, coordinator)
            if items is None:
                continue
            current = {i["key"]: i for i in items}
            for key, item in current.items():
                before = seen.get(key)
                if before is None or item["rank"] > before["rank"]:
                    self.hass.bus.async_fire(EVENT_NEW_WARNING, {
                        "type": {"met": "met_office", "flood": "flood", "river": "river"}[kind],
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
            for key in [k for k in seen if k.startswith(f"{kind}:") and k not in current]:
                if key in notified:
                    clears.append({"key": key, "message": notified.pop(key)["clear"]})
                del seen[key]
                changed = True

        for kind, items in outgoing.items():
            if len(items) > BATCH_LIMIT:
                names = {"met": "Met Office warnings", "flood": "flood warnings", "river": "rivers running high"}
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
