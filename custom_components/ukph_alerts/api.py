"""Fetch and parse the data sources. No Home Assistant imports, so it can be tested on its own."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import html
import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    EA_FLOODS_URL,
    EA_MEASURE_READINGS_URL,
    EA_STATION_PAGE,
    EA_STATIONS_URL,
    MAX_RIVER_STATIONS,
    RIVER_FETCH_CONCURRENCY,
    RIVER_TREND_THRESHOLD_M,
    FLOOD_SEVERITIES,
    MET_OFFICE_LEVELS,
    MET_OFFICE_URL,
    UKPH_API,
    UKPH_NEWS_CATEGORY_FALLBACK,
    UKPH_NEWS_CATEGORY_SLUG,
    UKPH_UTM,
    USER_AGENT,
)

UK_TZ = ZoneInfo("Europe/London")
TIMEOUT = aiohttp.ClientTimeout(total=30)
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

# "Yellow warning of wind affecting South West England: Dorset, Wiltshire valid from 0800 Thu 22 Feb to 1800 Thu 22 Feb"
MO_SUMMARY = re.compile(
    r"(?P<level>yellow|amber|red)\s+warning\s+of\s+(?P<hazard>.+?)\s+affecting\s+(?P<region>[^:]+?)\s*:\s*"
    r"(?P<areas>.*?)\s+valid\s+from\s+(?P<start>\d{4}\s+\w{3}\s+\d{1,2}\s+\w{3})\s+to\s+"
    r"(?P<end>\d{4}\s+\w{3}\s+\d{1,2}\s+\w{3})",
    re.IGNORECASE | re.DOTALL,
)
MO_TITLE = re.compile(
    r"(?P<level>yellow|amber|red)\s+warning\s+of\s+(?P<hazard>.+?)\s+affecting\s+(?P<region>.+)",
    re.IGNORECASE,
)
MO_TIME = re.compile(r"(\d{2})(\d{2})\s+(\w{3})\s+(\d{1,2})\s+(\w{3})")
TAG = re.compile(r"<[^>]+>")


class ApiError(Exception):
    """A source could not be fetched or parsed."""


def _text(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG.sub("", value or ""))).strip()


def parse_met_office_time(text: str, ref: datetime) -> datetime | None:
    """Parse '0800 Thu 22 Feb' (UK local, no year), choosing the year nearest ref whose weekday matches."""
    m = MO_TIME.fullmatch(text.strip())
    if not m:
        return None
    hh, mm, dow, day, mon = m.groups()
    month = MONTHS.get(mon.lower()[:3])
    if not month:
        return None
    candidates = []
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            candidates.append(datetime(year, month, int(day), int(hh) % 24, int(mm), tzinfo=UK_TZ))
        except ValueError:
            continue
    if not candidates:
        return None
    matching = [d for d in candidates if DAYS[d.weekday()] == dow.lower()[:3]] or candidates
    return min(matching, key=lambda d: abs(d - ref))


def parse_met_office(xml_text: str, now: datetime | None = None) -> list[dict[str, Any]]:
    """Parse a Met Office warnings RSS feed into warning dicts, most severe first."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as err:
        raise ApiError(f"Met Office feed is not valid XML: {err}") from err
    channel = root.find("channel")
    if channel is None:
        raise ApiError("Met Office feed has no channel")
    ref = now or datetime.now(UTC)
    if (pub := channel.findtext("pubDate")):
        try:
            ref = parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            pass

    warnings = []
    for item in channel.findall("item"):
        title = _text(item.findtext("title"))
        summary = _text(item.findtext("description"))
        enclosure = item.find("enclosure")
        warning: dict[str, Any] = {
            "level": None,
            "hazard": None,
            "region": None,
            "areas": [],
            "valid_from": None,
            "valid_to": None,
            "title": title,
            "summary": summary,
            "link": (item.findtext("link") or "").strip() or None,
            "id": (item.findtext("guid") or "").strip() or None,
            "image": enclosure.get("url") if enclosure is not None else None,
        }
        if m := MO_SUMMARY.search(summary):
            warning.update(
                level=m["level"].lower(),
                hazard=m["hazard"].strip().lower(),
                region=m["region"].strip(),
                areas=[a.strip() for a in m["areas"].split(",") if a.strip()],
                valid_from=parse_met_office_time(m["start"], ref),
                valid_to=parse_met_office_time(m["end"], ref),
            )
        elif m := MO_TITLE.search(title):
            # Unexpected summary wording: keep what the title gives us rather than drop the warning.
            warning.update(level=m["level"].lower(), hazard=m["hazard"].strip().lower(),
                           region=m["region"].strip())
        warnings.append(warning)

    warnings.sort(key=lambda w: -MET_OFFICE_LEVELS.index(w["level"] or "none"))
    return warnings


def parse_floods(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return active EA flood warnings (severity 1-3), most severe first."""
    items = data.get("items")
    if not isinstance(items, list):
        raise ApiError("EA response has no items list")
    warnings = []
    for x in items:
        level = x.get("severityLevel")
        if level not in FLOOD_SEVERITIES:
            continue
        area = x.get("floodArea") or {}
        warnings.append({
            "severity": FLOOD_SEVERITIES[level],
            "severity_level": level,
            "description": x.get("description"),
            "county": area.get("county"),
            "river_or_sea": area.get("riverOrSea"),
            "ea_area": x.get("eaAreaName"),
            "message": (x.get("message") or "").strip() or None,
            # EA gives no timezone marker on these; passed through raw (see docs/design.md).
            "time_raised": x.get("timeRaised"),
            "time_message_changed": x.get("timeMessageChanged"),
            "id": x.get("floodAreaID"),
            "link": f"https://check-for-flooding.service.gov.uk/target-area/{x['floodAreaID']}"
            if x.get("floodAreaID") else None,
        })
    warnings.sort(key=lambda w: w["severity_level"])
    return warnings


def add_utm(url: str | None) -> str | None:
    """Add the UKPH tracking tags before any #anchor."""
    if not url:
        return url
    parts = urlsplit(url)
    query = "&".join(filter(None, [parts.query, urlencode(UKPH_UTM)]))
    return urlunsplit(parts._replace(query=query))


def parse_news(posts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Parse the latest UKPH daily news post. Falls back to the excerpt if the structured fields are missing."""
    if not isinstance(posts, list):
        raise ApiError("UKPH response is not a list")
    if not posts:
        return None
    post = posts[0]
    meta = post.get("meta") or {}
    stories = meta.get("ukph_stories")
    if not isinstance(stories, list):
        stories = []
    published = None
    if post.get("date_gmt"):
        try:
            published = datetime.fromisoformat(post["date_gmt"]).replace(tzinfo=UTC)
        except ValueError:
            pass
    return {
        "title": _text((post.get("title") or {}).get("rendered")),
        "link": add_utm(post.get("link")),
        "published": published,
        "brief": (meta.get("ukph_brief") or "").strip()
        or _text((post.get("excerpt") or {}).get("rendered")),
        "stories": [
            {**s, "url": add_utm(s.get("url"))} for s in stories if isinstance(s, dict)
        ],
        "schema_version": meta.get("ukph_schema_version") or None,
    }


class UkphApi:
    """Thin async client for the three sources."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._news_category: int | None = None

    async def _get(self, url: str, params: dict[str, Any] | None = None, as_json: bool = True) -> Any:
        try:
            async with self._session.get(
                url, params=params, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}
            ) as resp:
                resp.raise_for_status()
                return await (resp.json(content_type=None) if as_json else resp.text())
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise ApiError(f"{url}: {err!r}") from err

    async def met_office(self, region: str) -> list[dict[str, Any]]:
        return parse_met_office(await self._get(MET_OFFICE_URL.format(region=region), as_json=False))

    async def floods(self, lat: float, lon: float, radius_km: float) -> list[dict[str, Any]]:
        # Rounded to ~1 km so the exact home location never leaves HA.
        params = {"lat": round(lat, 2), "long": round(lon, 2), "dist": radius_km}
        return parse_floods(await self._get(EA_FLOODS_URL, params))

    async def river_stations(self, lat: float, lon: float, radius_km: float) -> tuple[list[dict[str, Any]], int]:
        params = {"lat": round(lat, 2), "long": round(lon, 2), "dist": radius_km,
                  "parameter": "level", "_view": "full", "_limit": 1000}
        # Ask the EA for a slightly wider area, then trim to the true distance.
        params["dist"] = radius_km * 1.3
        return parse_river_stations(await self._get(EA_STATIONS_URL, params), lat, lon, radius_km)

    async def river_levels(self, stations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Latest reading for each station, a few requests at a time to go easy on the EA."""
        sem = asyncio.Semaphore(RIVER_FETCH_CONCURRENCY)

        async def one(station: dict[str, Any]) -> dict[str, Any]:
            async with sem:
                try:
                    data = await self._get(EA_MEASURE_READINGS_URL.format(measure=station["measure"]),
                                           {"_sorted": "", "_limit": 8})
                except ApiError:
                    data = {}  # one bad gauge shouldn't sink the rest
                return parse_river_readings(data, station)

        results = await asyncio.gather(*(one(s) for s in stations))
        if stations and all(r["level"] is None for r in results):
            raise ApiError("No river readings could be fetched")
        return results

    async def _category(self) -> int:
        if self._news_category is None:
            try:
                cats = await self._get(f"{UKPH_API}/categories",
                                       {"slug": UKPH_NEWS_CATEGORY_SLUG, "_fields": "id"})
                self._news_category = int(cats[0]["id"])
            except (ApiError, IndexError, KeyError, TypeError, ValueError):
                return UKPH_NEWS_CATEGORY_FALLBACK  # retry the lookup next time
        return self._news_category

    async def news(self) -> dict[str, Any] | None:
        params = {
            "categories": await self._category(),
            "per_page": 1,
            "_fields": "title,link,date_gmt,excerpt,meta.ukph_brief,meta.ukph_stories,meta.ukph_schema_version",
        }
        return parse_news(await self._get(f"{UKPH_API}/posts", params))


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from math import asin, cos, radians, sin, sqrt
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


def parse_river_stations(
    data: dict[str, Any], lat: float, lon: float, radius_km: float | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Usable level stations nearest first, capped. Returns (stations, total usable before the cap).

    Usable = has a river name, a typical range and a GOV.UK page (backup/intake gauges have none of these).
    """
    items = data.get("items")
    if not isinstance(items, list):
        raise ApiError("EA stations response has no items list")
    usable = []
    for s in items:
        scale = s.get("stageScale")
        if not (s.get("riverName") and s.get("RLOIid") and isinstance(scale, dict)):
            continue
        low, high = scale.get("typicalRangeLow"), scale.get("typicalRangeHigh")
        if low is None or high is None or s.get("lat") is None or s.get("long") is None:
            continue
        measures = s.get("measures") or []
        measures = measures if isinstance(measures, list) else [measures]
        ids = [m["@id"].rsplit("/", 1)[-1] for m in measures
               if isinstance(m, dict) and m.get("parameter") == "level" and m.get("@id")]
        # The typical range is in stage terms, so prefer the stage-datum measure.
        measure = next((m for m in ids if m.endswith("-mASD")), ids[0] if ids else None)
        if not measure:
            continue
        rloi = str(s["RLOIid"]).split(",")[0].strip()
        label = s.get("label") or s.get("town") or s["stationReference"]
        # "Bourn Brook at Bourn Brook" reads badly, so use the town when the station is named after its river.
        place = (s.get("town") or label) if label.lower() in s["riverName"].lower() else label
        usable.append({
            "ref": s["stationReference"],
            "station": place,
            "town": s.get("town"),
            "river": s["riverName"],
            "measure": measure,
            "distance_km": round(_distance_km(lat, lon, float(s["lat"]), float(s["long"])), 1),
            "typical_low": float(low),
            "typical_high": float(high),
            "highest_recent": (scale.get("highestRecent") or {}).get("value"),
            "max_on_record": (scale.get("maxOnRecord") or {}).get("value"),
            "link": EA_STATION_PAGE.format(rloi=rloi),
        })
    # The EA's own distance filter is looser than true distance (it returned 12.5 km for a 10 km search).
    if radius_km is not None:
        usable = [u for u in usable if u["distance_km"] <= radius_km]
    usable.sort(key=lambda x: x["distance_km"])
    return usable[:MAX_RIVER_STATIONS], len(usable)


def river_status(level: float, station: dict[str, Any]) -> str:
    if level < station["typical_low"]:
        return "low"
    if level <= station["typical_high"]:
        return "normal"
    recent = station.get("highest_recent")
    return "very_high" if recent is not None and level > recent else "high"


def parse_river_readings(data: dict[str, Any], station: dict[str, Any]) -> dict[str, Any]:
    """Latest level, status and one-hour trend for a station, from its newest readings."""
    readings = []
    for r in data.get("items") or []:
        try:
            readings.append((datetime.fromisoformat(r["dateTime"].replace("Z", "+00:00")), float(r["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not readings:
        return {**station, "level": None, "status": None, "trend": None, "change_1h_m": None, "reading_time": None}
    readings.sort(reverse=True)
    when, level = readings[0]
    # Compare against the reading closest to an hour earlier.
    older = min(readings[1:], key=lambda r: abs((when - r[0]).total_seconds() - 3600), default=None)
    change = round(level - older[1], 3) if older else None
    trend = None
    if change is not None:
        trend = ("rising" if change > RIVER_TREND_THRESHOLD_M
                 else "falling" if change < -RIVER_TREND_THRESHOLD_M else "steady")
    return {**station, "level": level, "status": river_status(level, station), "trend": trend,
            "change_1h_m": change, "reading_time": when}
