"""Parser tests (offline) plus an optional live smoke test: python -m tests.test_api [--live]."""

from datetime import UTC, datetime
import sys

from custom_components.ukph_alerts.api import (
    add_utm,
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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
    if "--live" in sys.argv:
        import asyncio
        asyncio.run(live())
