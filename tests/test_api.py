"""Parser tests (offline) plus an optional live smoke test: python -m tests.test_api [--live]."""

from datetime import UTC, datetime
import sys

from custom_components.ukph_alerts.api import (
    add_utm,
    parse_grid,
    parse_sepa_floods,
    parse_threat,
    irish_grid_to_wgs84,
    parse_river_readings,
    parse_river_stations,
    river_status,
    parse_floods,
    parse_met_office,
    parse_met_office_time,
    parse_news,
)

MO_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<title>Met Office warnings for South West England</title>
<pubDate>Wed, 21 Feb 2024 16:00:00 GMT</pubDate>
<item>
<title>Yellow warning of wind affecting South West England</title>
<link>https://www.metoffice.gov.uk/weather/warnings-and-advice/uk-warnings#?date=2024-02-22</link>
<description>Yellow warning of wind affecting South West England: Bournemouth Christchurch and Poole, Dorset, Wiltshire valid from 0800 Thu 22 Feb to 1800 Thu 22 Feb</description>
<guid isPermaLink="false">https://www.metoffice.gov.uk/weather/warnings-and-advice/uk-warnings#?date=2024-02-22&amp;id=603a4c83</guid>
<enclosure url="https://data.consumer-digital.api.metoffice.gov.uk/v1/warnings/rss/image/yellow-wind.png" length="15776" type="image/png"/>
</item>
<item>
<title>Amber warning of rain affecting South West England</title>
<link>https://www.metoffice.gov.uk/x</link>
<description>Some wording the parser has never seen</description>
</item>
</channel></rss>"""


def test_met_office():
    w = parse_met_office(MO_SAMPLE)
    assert len(w) == 2
    assert w[0]["level"] == "amber" and w[0]["hazard"] == "rain"  # most severe first; title fallback
    y = w[1]
    assert y["level"] == "yellow" and y["hazard"] == "wind"
    assert y["areas"] == ["Bournemouth Christchurch and Poole", "Dorset", "Wiltshire"]
    assert y["valid_from"].isoformat() == "2024-02-22T08:00:00+00:00"  # GMT in Feb
    assert y["valid_to"].isoformat() == "2024-02-22T18:00:00+00:00"
    assert y["image"].endswith("yellow-wind.png")


def test_met_office_year_rollover_and_bst():
    ref = datetime(2026, 12, 30, 12, tzinfo=UTC)
    d = parse_met_office_time("0600 Fri 01 Jan", ref)
    assert d.year == 2027 and d.weekday() == 4
    d = parse_met_office_time("0900 Wed 14 Oct", datetime(2026, 10, 14, tzinfo=UTC))
    assert d.isoformat() == "2026-10-14T09:00:00+01:00"  # BST
    assert parse_met_office_time("2400 Wed 14 Oct", datetime(2026, 10, 14, tzinfo=UTC)).hour == 0


def test_met_office_empty():
    xml = '<rss version="2.0"><channel><title>x</title><pubDate>Wed, 14 Oct 2026 18:00:41 GMT</pubDate></channel></rss>'
    assert parse_met_office(xml) == []


def test_floods():
    data = {"items": [
        {"severityLevel": 4, "floodAreaID": "a"},
        {"severityLevel": 3, "floodAreaID": "b", "description": "River X", "floodArea": {"county": "Cambs"}},
        {"severityLevel": 1, "floodAreaID": "c"},
    ]}
    w = parse_floods(data)
    assert [x["severity"] for x in w] == ["severe_flood_warning", "flood_alert"]
    assert w[1]["county"] == "Cambs"


def test_utm():
    assert add_utm("https://x.uk/p/#a") == "https://x.uk/p/?utm_source=homeassistant&utm_medium=integration#a"
    assert add_utm("https://x.uk/p/?q=1") == "https://x.uk/p/?q=1&utm_source=homeassistant&utm_medium=integration"


def test_news_fallback():
    n = parse_news([{"title": {"rendered": "Daily &#8212; News"}, "link": "https://x.uk/p/",
                     "date_gmt": "2026-10-14T07:40:34", "excerpt": {"rendered": "<p>Short &amp; sweet</p>"}}])
    assert n["title"] == "Daily — News" and n["brief"] == "Short & sweet" and n["stories"] == []
    assert n["published"].isoformat() == "2026-10-14T07:40:34+00:00"
    assert parse_news([]) is None


def test_news_sample():
    import json, pathlib
    p = pathlib.Path(__file__).parent.parent / "docs" / "ukph-feed-sample-2026-10-14.json"
    if not p.exists():  # local-only sample, not in the public repo
        return
    n = parse_news(json.loads(p.read_text()))
    assert len(n["brief"]) == 643 and len(n["stories"]) == 22 and n["schema_version"] == 1
    assert all("utm_source=homeassistant" in s["url"] and s["url"].index("?") < s["url"].index("#")
               for s in n["stories"])


def test_guess_region():
    from custom_components.ukph_alerts.config_flow import guess_region
    cases = {(52.2, -0.2): "ee", (51.5, -0.12): "se", (53.48, -2.24): "nw", (55.95, -3.19): "dg",
             (57.48, -4.22): "he", (54.6, -5.93): "ni", (51.48, -3.18): "wl", (50.37, -4.14): "sw",
             (52.48, -1.9): "wm", (53.8, -1.55): "yh", (54.97, -1.61): "ne", (57.15, -2.09): "gr",
             (55.86, -4.25): "st", (56.46, -2.97): "ta", (60.15, -1.15): "os", (52.95, -1.15): "em",
             (52.2, -0.2): "ee", (51.62, -3.94): "wl", (53.22, -4.13): "wl", (52.57, -0.24): "ee",
             (51.38, -2.36): "sw", (51.9, -2.08): "sw", (53.0, -2.18): "wm", (52.04, -0.76): "se",
             (48.85, 2.35): "UK", (None, None): "UK"}
    wrong = {k: (guess_region(*k), v) for k, v in cases.items() if guess_region(*k) != v}
    assert not wrong, wrong


def test_river_stations():
    data = {"items": [
        {"stationReference": "A", "label": "St Neots", "riverName": "River Great Ouse", "RLOIid": "6174",
         "lat": 52.23, "long": -0.27, "stageScale": {"typicalRangeLow": 0.82, "typicalRangeHigh": 1.1,
                                                    "highestRecent": {"value": 1.53}},
         "measures": [{"@id": "x/A-level-stage-i-15_min-m", "parameter": "level"},
                      {"@id": "x/A-level-stage-i-15_min-mASD", "parameter": "level"}]},
        {"stationReference": "B", "label": "Backup", "lat": 52.2, "long": -0.2,  # no river/RLOI: skipped
         "measures": {"@id": "x/B-level-stage-i-15_min-mAOD", "parameter": "level"}},
        {"stationReference": "C", "label": "Far", "riverName": "Kym", "RLOIid": "1", "lat": 52.6, "long": -0.2,
         "stageScale": {"typicalRangeLow": 0.1, "typicalRangeHigh": 1.3},
         "measures": {"@id": "x/C-level-stage-i-15_min-mASD", "parameter": "level"}},
    ]}
    stations, total = parse_river_stations(data, 52.2, -0.2)
    assert total == 2 and [s["ref"] for s in stations] == ["A", "C"]  # nearest first, backup skipped
    a = stations[0]
    assert a["measure"] == "A-level-stage-i-15_min-mASD"  # stage datum preferred
    assert a["link"] == "https://check-for-flooding.service.gov.uk/station/6174"
    assert river_status(0.5, a) == "low" and river_status(1.0, a) == "normal"
    assert river_status(1.2, a) == "high" and river_status(1.6, a) == "very_high"
    near, n = parse_river_stations(data, 52.2, -0.2, radius_km=10)
    assert n == 1 and [s["ref"] for s in near] == ["A"]  # C is ~44 km away


def test_river_trend():
    st = {"typical_low": 0.8, "typical_high": 1.1, "highest_recent": 1.5}
    t = ["2026-10-15T01:15:00Z", "2026-10-15T01:00:00Z", "2026-10-15T00:45:00Z", "2026-10-15T00:30:00Z", "2026-10-15T00:15:00Z"]
    r = parse_river_readings({"items": [{"dateTime": d, "value": v} for d, v in zip(t, [0.859, 0.854, 0.849, 0.844, 0.837])]}, st)
    assert r["level"] == 0.859 and r["trend"] == "rising" and r["change_1h_m"] == 0.022
    r = parse_river_readings({"items": [{"dateTime": d, "value": 0.9} for d in t]}, st)
    assert r["trend"] == "steady" and r["status"] == "normal"
    assert parse_river_readings({"items": []}, st)["level"] is None


def test_threat():
    xml = ("<rss><channel><item><title>Current Threat Level: SEVERE</title><description>&lt;p&gt;The current national "
           "threat level is SEVERE. &amp;nbsp;The threat to Northern Ireland from Northern Ireland-related terrorism is "
           "SUBSTANTIAL.&lt;/p&gt;</description><pubDate>Thursday, April 30, 2026 - 06:09</pubDate></item></channel></rss>")
    t = parse_threat(xml)
    assert t["level"] == "severe" and t["ni_level"] == "substantial"


def test_grid():
    issued = ("From : Power System Manager ELECTRICITY MARGIN NOTICE An ELECTRICITY MARGIN NOTICE has been issued ... "
              "For the period: from 16:00 hrs to 23:00 hrs on Tuesday   06/10/2026   There is a reduced margin")
    cancelled = ("NOTIFICATION CANCELLATION of GB TRANSMISSION SYSTEM WARNING The GB Transmission System Warning "
                 "ELECTRICITY MARGIN NOTICE issued for the period from  16:00 hrs to 23:00 hrs on Tuesday   06/10/2026 has been cancelled")
    assist = ("A request for Emergency Assistance has been agreed on a GB connected Interconnector. GB net flow will "
              "increase by 700 MW between 16:52 12/10/2026 to 18:00 12/10/2026.")
    noise = {"warningType": "SO-SO TRADES", "warningText": "prices", "publishTime": "2026-10-06T10:00:00Z"}
    emn = {"warningType": "ELECTRICITY MARGIN NOTICE", "warningText": issued, "publishTime": "2026-10-06T11:00:00Z"}
    during = datetime(2026, 10, 6, 17, 0, tzinfo=UTC)  # 18:00 BST, inside the 16:00-23:00 window
    g = parse_grid({"data": [noise, emn]}, during)
    assert g["status"] == "margin_notice" and len(g["active"]) == 1 and "16:00" in g["active"][0]["summary"]
    g = parse_grid({"data": [emn, {"warningType": "ELECTRICITY MARGIN NOTICE", "warningText": cancelled,
                                   "publishTime": "2026-10-06T14:51:00Z"}]}, during)
    assert g["status"] == "normal" and g["recent"][0]["cancelled"]
    g = parse_grid({"data": [{"warningType": "OTHER", "warningText": assist, "publishTime": "2026-10-12T15:49:00Z"}]},
                   datetime(2026, 10, 12, 16, 0, tzinfo=UTC))
    assert g["status"] == "normal" and "700 MW" in g["active"][0]["summary"]  # informative, not a warning


def test_sepa_floods():
    f = [{"attributes": {"name": "River Tay at Perth", "severity": "Flood Warning", "message": "<p>Act now</p>", "id": 7}},
         {"attributes": {"name": "Tayside", "severity": None, "id": 8}}]
    w = parse_sepa_floods(f, 3)
    assert [x["severity"] for x in w] == ["flood_warning", "flood_alert"] and w[0]["message"] == "Act now"


def test_irish_grid():
    lat, lon = irish_grid_to_wgs84(333500, 373500)  # central Belfast
    assert abs(lat - 54.6) < 0.02 and abs(lon + 5.93) < 0.02


async def live():
    import aiohttp
    from custom_components.ukph_alerts.api import UkphApi
    async with aiohttp.ClientSession() as s:
        api = UkphApi(s)
        print("met office UK:", await api.met_office("UK"))
        f = await api.floods(52.2, -0.2, 50)
        print("floods within 50km:", len(f), f[:1])
        n = await api.news()
        print("news:", n["title"], n["link"], n["published"], len(n["brief"]), len(n["stories"]))
        print("category id:", api._news_category)
        st, total = await api.river_stations(52.2, -0.2, 10)
        lv = await api.river_levels(st)
        print("rivers:", total, "usable;", [(x["station"], x["level"], x["status"], x["trend"]) for x in lv])


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    if "--live" in sys.argv:
        import asyncio
        asyncio.run(live())
