"""Alert logic tests with stub HA objects: python tests/test_alerts.py (needs HA installed)."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from custom_components.ukph_alerts import alerts as al


class FakeStore:
    saved = None

    def __init__(self, *a, **k):
        pass

    async def async_load(self):
        return FakeStore.saved

    async def async_save(self, data):
        import copy
        FakeStore.saved = copy.deepcopy(data)


class Coord:
    def __init__(self, data):
        self.data, self.last_update_success = data, True

    def async_add_listener(self, cb):
        return lambda: None


def make(met=None, floods=None, rivers=None, opts=None, power=None, health=None, grid=None, threat=None):
    sent, events = [], []
    hass = SimpleNamespace(
        bus=SimpleNamespace(async_fire=lambda t, d: events.append(d)),
        services=SimpleNamespace(has_service=lambda d, s: True,
                                 async_call=lambda d, s, p, blocking=True: _rec(sent, p)),
    )
    entry = SimpleNamespace(entry_id="e1", async_on_unload=lambda f: None,
                            runtime_data=SimpleNamespace(met_office=Coord(met or []), floods=Coord(floods or []),
                                                         rivers=Coord({"stations": rivers or []}),
                                                         power=Coord(power or []),
                                                         health=Coord(health or {"heat": None, "cold": None}),
                                                         grid=Coord(grid or {"active": []}),
                                                         threat=Coord(threat)))
    a = al.UkphAlerter(hass, entry, {"notify_services": ["mobile_app_phone"], **(opts or {})})
    return a, entry, sent, events


async def _rec(sent, p):
    sent.append(p)


def W(level, wid="w1"):
    return {"id": wid, "level": level, "hazard": "rain", "areas": ["Cambs"], "link": "https://mo", "title": "t"}


def R(status, trend, ref="R1"):
    return {"ref": ref, "river": "Ouse", "station": "St Neots", "status": status, "trend": trend, "level": 1.6,
            "typical_low": 0.8, "typical_high": 1.1, "link": "https://gov"}


async def run():
    with patch.object(al, "Store", FakeStore), patch.object(al.dt_util, "as_local", lambda d: d):
        # yellow: event fired, but below the amber threshold, so no phone alert
        FakeStore.saved = None
        a, e, sent, events = make(met=[W("yellow")])
        await a.async_start()
        assert len(events) == 1 and not sent
        # upgrade to amber: upgrade event + alert
        e.runtime_data.met_office.data = [W("amber")]
        await a._evaluate()
        assert events[-1]["change"] == "upgrade" and len(sent) == 1 and "Amber" in sent[0]["title"]
        assert sent[0]["data"]["url"] == "https://mo"
        # same again: nothing new
        await a._evaluate()
        assert len(sent) == 1 and len(events) == 2
        # restart: state persisted, so no re-send
        a2, e2, sent2, _ = make(met=[W("amber")])
        await a2.async_start()
        assert not sent2
        # source outage must not count as all clear
        e2.runtime_data.met_office.last_update_success = False
        e2.runtime_data.met_office.data = []
        await a2._evaluate()
        assert not sent2
        # genuinely gone: all clear
        e2.runtime_data.met_office.last_update_success = True
        await a2._evaluate()
        assert len(sent2) == 1 and sent2[0]["title"] == "✅ All clear"

        # rivers: very high but steady doesn't start an alert; rising does; then stays active while steady
        FakeStore.saved = None
        a, e, sent, _ = make(rivers=[R("very_high", "steady")])
        await a.async_start()
        assert not sent
        e.runtime_data.rivers.data = {"stations": [R("very_high", "rising")]}
        await a._evaluate()
        assert len(sent) == 1
        e.runtime_data.rivers.data = {"stations": [R("very_high", "steady")]}
        await a._evaluate()
        assert len(sent) == 1
        e.runtime_data.rivers.data = {"stations": [R("high", "falling")]}  # dropped below alert level
        await a._evaluate()
        assert sent[-1]["title"] == "✅ All clear"

        # floods: 5 new warnings at once are rolled into one summary
        FakeStore.saved = None
        fl = [{"id": f"f{i}", "severity": "flood_warning", "description": f"River {i}", "message": "m", "link": "l"} for i in range(5)]
        a, e, sent, _ = make(floods=fl)
        await a.async_start()
        assert len(sent) == 1 and sent[0]["title"].startswith("5 new flood warnings")
        # power cuts: default "near" = within 2 km only, unplanned only
        FakeStore.saved = None
        cut = lambda i, d, planned=False: {"id": i, "distance_km": d, "planned": planned, "customers": 40,
                                           "network": "UK Power Networks", "estimated_restore": None, "cause": "x", "link": "l"}
        a, e, sent, _ = make(power=[cut("far", 6.0), cut("plan", 0.5, True)])
        await a.async_start()
        assert not sent
        e.runtime_data.power.data = [cut("far", 6.0), cut("near", 1.2)]
        await a._evaluate()
        assert len(sent) == 1 and "1.2 km" in sent[0]["title"]
        e.runtime_data.power.data = [cut("far", 6.0)]
        await a._evaluate()
        assert sent[-1]["title"] == "✅ All clear"

        # health: amber alert, then the all clear actually fires (bug caught in review)
        FakeStore.saved = None
        hh = lambda lvl: {"heat": {"level": lvl, "region": "East of England", "summary": "s", "link": "l"}, "cold": None}
        a, e, sent, _ = make(health=hh("amber"))
        await a.async_start()
        assert len(sent) == 1 and "Amber heat-health" in sent[0]["title"]
        e.runtime_data.health.data = hh("green")
        await a._evaluate()
        assert len(sent) == 2 and sent[-1]["title"] == "✅ All clear"

        # threat: remember on first run, alert on change
        FakeStore.saved = None
        a, e, sent, events = make(threat={"level": "severe", "summary": "s", "link": "l"})
        await a.async_start()
        assert not sent
        e.runtime_data.threat.data = {"level": "substantial", "summary": "s", "link": "l"}
        await a._evaluate()
        assert len(sent) == 1 and "lowered to SUBSTANTIAL" in sent[0]["title"] and events[-1]["change"] == "downgrade"

        # SEPA rivers have a state but no level/range: state-only message, and other alerts still go out
        FakeStore.saved = None
        sepa = {"ref": "sepa-1", "river": "Tweed", "station": "Peebles", "status": "high", "trend": None,
                "level": None, "typical_low": None, "typical_high": None, "link": "https://sepa", "source": "SEPA"}
        a, e, sent, _ = make(met=[W("amber")], rivers=[sepa], opts={"alert_rivers": "high"})
        await a.async_start()
        assert len(sent) == 2
        river = next(s for s in sent if "Tweed" in s["title"])
        assert river["message"] == "Tweed at Peebles: high (SEPA)."

        # a malformed record is skipped on its own; it isn't mistaken for cleared, and other items still alert
        FakeStore.saved = None
        good = {"id": "f1", "severity": "flood_warning", "description": "Ouse", "link": "l"}
        a, e, sent, _ = make(met=[W("amber")], floods=[good])
        await a.async_start()
        assert len(sent) == 2
        e.runtime_data.floods.data = [{"id": "f1", "description": "Ouse"}, {"id": "f2", "severity": "flood_warning",
                                                                           "description": "Cam"}]
        await a._evaluate()
        assert len(sent) == 3 and "Cam" in sent[-1]["title"]  # f1 unreadable: no false all-clear
        assert "flood:f1" in a._state["notified"]

        # a source that blows up entirely doesn't stop the others
        FakeStore.saved = None
        a, e, sent, _ = make(met=[W("amber")])
        e.runtime_data.grid.data = "broken"  # .get() on a str raises AttributeError
        await a.async_start()
        assert len(sent) == 1
    print("ok alerts")


asyncio.run(run())
