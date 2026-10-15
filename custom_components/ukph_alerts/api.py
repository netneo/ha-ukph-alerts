"""Fetch and parse the data sources. No Home Assistant imports, so it can be tested on its own."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import html
import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    ELEXON_SYSWARN,
    MI5_FEED,
    MI5_PAGE,
    NGED_FAULTS,
    NGED_RESOURCE,
    NIE_FAULTS,
    NPG_FAULTS,
    POWER_NETWORK_NAMES,
    POWER_NETWORK_PAGES,
    SEPA_ARCGIS,
    SEPA_FLOOD_LAYERS,
    SEPA_PAGE,
    SEPA_RIVERS_LAYER,
    SSEN_FAULTS,
    THREAT_LEVELS,
    UKHSA_ALERTS,
    UKHSA_PAGE,
    UKHSA_REGION_POINTS,
    UKPN_FAULTS,
    GRID_STATUSES,
    HEALTH_LEVELS,
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

    async def _sepa(self, layer: str, lat: float, lon: float, radius_km: float) -> list[dict[str, Any]]:
        params = {"where": "1=1", "geometry": f"{round(lon, 2)},{round(lat, 2)}", "geometryType": "esriGeometryPoint",
                  "inSR": 4326, "distance": radius_km, "units": "esriSRUnit_Kilometer", "outFields": "*",
                  "returnGeometry": "true", "outSR": 4326, "f": "json"}
        data = await self._get(f"{SEPA_ARCGIS}/{layer}/FeatureServer/0/query", params)
        if not isinstance(data, dict) or "error" in data:
            raise ApiError(f"SEPA {layer}: {data.get('error') if isinstance(data, dict) else data}")
        return data.get("features") or []

    async def floods(self, lat: float, lon: float, radius_km: float, scotland: bool = False) -> list[dict[str, Any]]:
        """EA (England) and SEPA (Scotland) together. Only the home nation's source failing counts as a failure,
        so an outage there is never mistaken for an all clear."""
        # Rounded to ~1 km so the exact home location never leaves HA.
        params = {"lat": round(lat, 2), "long": round(lon, 2), "dist": radius_km}
        warnings: list[dict[str, Any]] = []
        try:
            warnings += parse_floods(await self._get(EA_FLOODS_URL, params))
        except ApiError:
            if not scotland:
                raise
        for layer, default in SEPA_FLOOD_LAYERS.items():
            try:
                warnings += parse_sepa_floods(await self._sepa(layer, lat, lon, radius_km), default)
            except ApiError:
                if scotland:
                    raise
        warnings.sort(key=lambda w: w["severity_level"])
        return warnings

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

    async def sepa_rivers(self, lat: float, lon: float, radius_km: float) -> list[dict[str, Any]]:
        return parse_sepa_rivers(await self._sepa(SEPA_RIVERS_LAYER, lat, lon, radius_km), lat, lon)

    async def threat(self) -> dict[str, Any]:
        return parse_threat(await self._get(MI5_FEED, as_json=False))

    async def grid(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        start = now - timedelta(days=7)
        params = {"publishDateTimeFrom": f"{start:%Y-%m-%dT%H:%MZ}", "publishDateTimeTo": f"{now:%Y-%m-%dT%H:%MZ}",
                  "format": "json"}
        return parse_grid(await self._get(ELEXON_SYSWARN, params), now)

    async def health(self, kind: str, region_code: str) -> dict[str, Any]:
        return parse_health(await self._get(UKHSA_ALERTS.format(kind=kind, code=region_code)), kind)

    async def power_cuts(self, networks: list[str], lat: float, lon: float, radius_km: float) -> list[dict[str, Any]]:
        """Live power cuts within the radius from each network serving the area. Fails only if every network failed."""
        geo = f"within_distance(geopoint, geom'POINT({round(lon, 2)} {round(lat, 2)})', {radius_km * 1.2}km)"
        requests = {
            "ukpn": (UKPN_FAULTS, {"where": geo, "limit": 100}),
            "npg": (NPG_FAULTS, {"where": geo, "limit": 100}),
            "nged": (NGED_FAULTS, {"resource_id": NGED_RESOURCE, "limit": 1000}),
            "ssen": (SSEN_FAULTS, None),
            "nie": (NIE_FAULTS, None),
        }
        cuts: list[dict[str, Any]] = []
        failed = []
        for net in networks:
            url, params = requests[net]
            try:
                cuts += POWER_PARSERS[net](await self._get(url, params))
            except (ApiError, AttributeError, TypeError) as err:
                failed.append(f"{net}: {err}")
        if networks and len(failed) == len(networks):
            raise ApiError("; ".join(failed))
        for c in cuts:
            c["distance_km"] = round(_distance_km(lat, lon, c["lat"], c["lon"]), 1)
            del c["lat"], c["lon"]  # don't publish exact fault locations in HA attributes
        near = [c for c in cuts if c["distance_km"] <= radius_km]
        near.sort(key=lambda c: (c["planned"], c["distance_km"]))
        return near

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


# --- Scotland (SEPA) ---------------------------------------------------------------------------------

def _sepa_severity(text: str | None, default: int) -> int:
    t = (text or "").lower()
    if "severe" in t:
        return 1
    if "warning" in t:
        return 2
    if "alert" in t:
        return 3
    return default


def parse_sepa_floods(features: list[dict[str, Any]], default_level: int) -> list[dict[str, Any]]:
    """SEPA flood alert/warning points (the layers only hold warnings in force) in the same shape as EA's."""
    out = []
    for f in features:
        a = f.get("attributes") or {}
        level = _sepa_severity(a.get("severity"), default_level)
        if level not in FLOOD_SEVERITIES:
            continue
        out.append({
            "severity": FLOOD_SEVERITIES[level],
            "severity_level": level,
            "description": a.get("name") or a.get("fwa_name"),
            "county": a.get("local_authority"),
            "river_or_sea": a.get("source_of_flood"),
            "ea_area": None,
            "message": _text(a.get("message")) or None,
            "time_raised": a.get("startTime"),
            "time_message_changed": a.get("updatedTime"),
            "id": f"sepa-{a.get('id') or a.get('ObjectId')}",
            "link": a.get("uri") or SEPA_PAGE,
            "source": "SEPA",
        })
    return out


def parse_sepa_rivers(features: list[dict[str, Any]], lat: float, lon: float) -> list[dict[str, Any]]:
    """SEPA stations give a High/Normal/Low state but no level in metres, and no trend we can trust yet."""
    out = []
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        state = (a.get("state") or "").strip().lower()
        if state not in ("high", "normal", "low") or g.get("y") is None:
            continue
        out.append({
            "ref": f"sepa-{a.get('station_no')}",
            "station": a.get("station_name"),
            "town": None,
            "river": a.get("river_name") or a.get("catchment_name"),
            "distance_km": round(_distance_km(lat, lon, float(g["y"]), float(g["x"])), 1),
            "level": None, "typical_low": None, "typical_high": None, "highest_recent": None,
            "max_on_record": None, "change_1h_m": None, "trend": None,
            "status": state, "reading_time": a.get("timestamp"),
            "link": SEPA_PAGE, "source": "SEPA",
        })
    return out


# --- MI5 threat level --------------------------------------------------------------------------------

def parse_threat(xml_text: str) -> dict[str, Any]:
    try:
        item = ET.fromstring(xml_text).find("channel/item")
    except ET.ParseError as err:
        raise ApiError(f"MI5 feed is not valid XML: {err}") from err
    if item is None:
        raise ApiError("MI5 feed has no item")
    text = " ".join(filter(None, [_text(item.findtext("title")), _text(item.findtext("description"))]))
    levels = "|".join(THREAT_LEVELS)
    national = re.search(rf"national threat level is ({levels})", text, re.I) or re.search(
        rf"Threat Level:\s*({levels})", text, re.I)
    ni = re.search(rf"Northern Ireland-related terrorism is ({levels})", text, re.I)
    if not national:
        raise ApiError(f"Couldn't read the threat level from: {text[:120]}")
    return {
        "level": national.group(1).lower(),
        "ni_level": ni.group(1).lower() if ni else None,
        "summary": _text(item.findtext("description")),
        "updated": _text(item.findtext("pubDate")),
        "link": MI5_PAGE,
    }


# --- Grid notices (NESO via Elexon) ------------------------------------------------------------------

GRID_KEEP = {  # warningType -> status it implies while in force
    "ELECTRICITY MARGIN NOTICE": "margin_notice",
    "HIGH RISK OF DEMAND REDUCTION": "high_risk",
    "DEMAND CONTROL IMMINENT": "demand_control",
    "CAPACITY MARKET NOTICE": "margin_notice",
}
PERIOD = re.compile(r"from\s+(\d{1,2}):(\d{2})\s*hrs\s+to\s+(\d{1,2}):(\d{2})\s*hrs\s+on\s+\w+\s+(\d{2})/(\d{2})/(\d{4})", re.I)
ASSIST = re.compile(r"between\s+(\d{1,2}):(\d{2})\s+(\d{2})/(\d{2})/(\d{4})\s+to\s+(\d{1,2}):(\d{2})\s+(\d{2})/(\d{2})/(\d{4})", re.I)
MW = re.compile(r"increase by\s+(\d+)\s*MW", re.I)


def _uk(y, mo, d, h, mi) -> datetime:
    return datetime(int(y), int(mo), int(d), int(h) % 24, int(mi), tzinfo=UK_TZ)


def parse_grid(data: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """Current grid status from NESO's system warnings. Routine trading/IT notices are dropped."""
    now = now or datetime.now(UTC)
    notices: dict[str, dict[str, Any]] = {}
    for x in sorted(data.get("data") or [], key=lambda r: r.get("publishTime") or ""):
        wtype = (x.get("warningType") or "").upper()
        text = re.sub(r"\s+", " ", (x.get("warningText") or "").replace("\\n", " "))
        published = x.get("publishTime")
        if wtype in GRID_KEEP:
            m = PERIOD.search(text)
            if not m:
                continue
            h1, m1, h2, m2, d, mo, y = m.groups()
            start, end = _uk(y, mo, d, h1, m1), _uk(y, mo, d, h2, m2)
            key = f"{wtype}:{start.isoformat()}"
            if "CANCELLATION" in text.upper() or "HAS BEEN CANCELLED" in text.upper():
                if key in notices:
                    notices[key]["cancelled"] = True
                continue
            notices[key] = {"type": wtype.title(), "status": GRID_KEEP[wtype], "start": start, "end": end,
                            "published": published, "cancelled": False,
                            "summary": f"{wtype.title()} for {start:%H:%M}–{end:%H:%M} on {start:%a %d %b}"}
        elif "EMERGENCY ASSISTANCE" in text.upper():
            m = ASSIST.search(text)
            if not m:
                continue
            h1, m1, d1, mo1, y1, h2, m2, d2, mo2, y2 = m.groups()
            start, end = _uk(y1, mo1, d1, h1, m1), _uk(y2, mo2, d2, h2, m2)
            mw = MW.search(text)
            notices[f"assist:{published}"] = {
                "type": "Emergency assistance", "status": "normal", "start": start, "end": end,
                "published": published, "cancelled": False,
                "summary": f"NESO asked for emergency power from abroad"
                           f"{f' ({mw.group(1)} MW)' if mw else ''}, {start:%H:%M}–{end:%H:%M} on {start:%a %d %b}"}
    active = [n for n in notices.values() if not n["cancelled"] and n["end"] > now]
    status = max((n["status"] for n in active), key=GRID_STATUSES.index, default="normal")
    recent = sorted(notices.values(), key=lambda n: n["published"] or "", reverse=True)[:10]
    return {"status": status, "active": sorted(active, key=lambda n: n["start"]), "recent": recent}


# --- UKHSA weather-health alerts ---------------------------------------------------------------------

def guess_ukhsa_region(lat: float | None, lon: float | None) -> str | None:
    """The English region for HA's home location, or None outside England (UKHSA alerts are England-only)."""
    from math import cos, radians
    from .const import MET_OFFICE_REGION_POINTS
    if lat is None or lon is None or not (49.8 <= lat <= 56.0 and -6.5 <= lon <= 2.0):
        return None
    k = cos(radians(lat))
    nearest = lambda table: min(((r, p) for r, pts in table.items() for p in pts),
                                key=lambda rp: (rp[1][0] - lat) ** 2 + ((rp[1][1] - lon) * k) ** 2)[0]
    if nearest(MET_OFFICE_REGION_POINTS) in ("wl", "st", "dg", "ta", "gr", "he", "os", "ni"):
        return None
    return nearest(UKHSA_REGION_POINTS)


def parse_health(data: dict[str, Any], kind: str) -> dict[str, Any]:
    status = (data.get("status") or "").lower()
    if status not in HEALTH_LEVELS:
        raise ApiError(f"Unexpected UKHSA {kind} status: {data.get('status')!r}")
    return {
        "level": status,
        "region": data.get("geography_name"),
        "summary": _text(data.get("text")),
        "likelihood": data.get("likelihood"),
        "impact": data.get("impact"),
        "period_start": data.get("period_start"),
        "period_end": data.get("period_end"),
        "updated": data.get("refresh_date"),
        "link": UKHSA_PAGE.format(kind=kind),
    }


# --- Power cuts ----------------------------------------------------------------------------------------

def irish_grid_to_wgs84(e: float, n: float) -> tuple[float, float]:
    """Irish Grid (TM65) easting/northing to lat/lon. No datum shift: ~100 m out, fine for a radius check."""
    from math import atan, cos, degrees, radians, sin, sqrt, tan
    a, b, f0 = 6377340.189, 6356034.447, 1.000035
    lat0, lon0, e0, n0 = radians(53.5), radians(-8.0), 200000.0, 250000.0
    e2 = 1 - b * b / (a * a)
    nn = (a - b) / (a + b)

    def meridional(phi: float) -> float:
        return b * f0 * ((1 + nn + 5 / 4 * nn ** 2 + 5 / 4 * nn ** 3) * (phi - lat0)
                         - (3 * nn + 3 * nn ** 2 + 21 / 8 * nn ** 3) * sin(phi - lat0) * cos(phi + lat0)
                         + (15 / 8 * nn ** 2 + 15 / 8 * nn ** 3) * sin(2 * (phi - lat0)) * cos(2 * (phi + lat0))
                         - 35 / 24 * nn ** 3 * sin(3 * (phi - lat0)) * cos(3 * (phi + lat0)))
    phi = lat0 + (n - n0) / (a * f0)
    for _ in range(10):
        m = meridional(phi)
        if abs(n - n0 - m) < 0.00001:
            break
        phi += (n - n0 - m) / (a * f0)
    nu = a * f0 / sqrt(1 - e2 * sin(phi) ** 2)
    rho = a * f0 * (1 - e2) / (1 - e2 * sin(phi) ** 2) ** 1.5
    eta2 = nu / rho - 1
    t = tan(phi)
    de = e - e0
    vii = t / (2 * rho * nu)
    viii = t / (24 * rho * nu ** 3) * (5 + 3 * t * t + eta2 - 9 * t * t * eta2)
    x = 1 / (cos(phi) * nu)
    xi = 1 / (cos(phi) * 6 * nu ** 3) * (nu / rho + 2 * t * t)
    lat = phi - vii * de ** 2 + viii * de ** 4
    lon = lon0 + x * de - xi * de ** 3
    return degrees(lat), degrees(lon)


def _cut(network: str, cid: Any, lat: Any, lon: Any, **kw: Any) -> dict[str, Any] | None:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    return {"network": POWER_NETWORK_NAMES[network], "id": str(cid), "lat": lat, "lon": lon,
            "link": POWER_NETWORK_PAGES[network], **kw}


def _int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def parse_power_ukpn(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in data.get("results") or []:
        if r.get("restoreddatetime"):
            continue
        g = r.get("geopoint") or {}
        planned = (r.get("powercuttype") or "").lower() == "planned"
        c = _cut("ukpn", r.get("incidentreference"), g.get("lat"), g.get("lon"), planned=planned,
                 customers=_int(r.get("nocustomeraffected")) or _int(r.get("noplannedcustomers")),
                 start=r.get("creationdatetime") if not planned else r.get("planneddate"),
                 estimated_restore=r.get("estimatedrestorationdate"),
                 cause=_text(r.get("incidentcategorycustomerfriendlydescription") or r.get("mainmessage")),
                 postcodes=(r.get("postcodesaffected") or "").replace(";", ", "))
        if c:
            out.append(c)
    return out


def parse_power_npg(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in data.get("results") or []:
        planned = "planned" in (r.get("natureofoutage") or "").lower()
        pcs = r.get("postcode")
        c = _cut("npg", r.get("reference"), r.get("lat"), r.get("lng"), planned=planned,
                 customers=_int(r.get("totalconfirmedpowercut")),
                 start=r.get("loggedtime"), estimated_restore=r.get("estimatedtimetillresolution"),
                 cause=_text(r.get("reason") or r.get("natureofoutage")),
                 postcodes=", ".join(pcs) if isinstance(pcs, list) else str(pcs or ""))
        if c:
            out.append(c)
    return out


def parse_power_nged(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in (data.get("result") or {}).get("records") or []:
        planned = str(r.get("Planned")).lower() == "true"
        c = _cut("nged", r.get("Incident ID"), r.get("Location Latitude"), r.get("Location Longitude"),
                 planned=planned, customers=_int(r.get("Confirmed Off")),
                 start=r.get("Start Time"), estimated_restore=r.get("ETR"),
                 cause=_text(r.get("Category")), postcodes=r.get("Postcodes") or "")
        if c:
            out.append(c)
    return out


def parse_power_ssen(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in data.get("Faults") or []:
        if r.get("resolved"):
            continue
        msg = _text(r.get("message"))
        c = _cut("ssen", r.get("reference"), r.get("latitude"), r.get("longitude"),
                 planned="planned work" in msg.lower(), customers=_int(r.get("affectedCustomerCount")),
                 start=r.get("loggedAt"), estimated_restore=r.get("estimatedRestoration"),
                 cause=msg[:300], postcodes=r.get("name") or "")
        if c:
            out.append(c)
    return out


def parse_power_nie(data: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for r in data.get("outageMessage") or []:
        try:
            e, n = (float(v) for v in str((r.get("point") or {}).get("coordinates")).split(","))
        except ValueError:
            continue
        lat, lon = irish_grid_to_wgs84(e, n)
        c = _cut("nie", r.get("outageId"), lat, lon, planned=(r.get("outageType") or "").lower() != "fault",
                 customers=_int(r.get("numCustAffected")), start=r.get("startTime"),
                 estimated_restore=r.get("estRestoreFullDateTime"),
                 cause=_text(r.get("statusMessage") or r.get("causeMessage")),
                 postcodes=(r.get("postCode") or "").replace(";", ", "))
        if c:
            out.append(c)
    return out


POWER_PARSERS = {"ukpn": parse_power_ukpn, "npg": parse_power_npg, "nged": parse_power_nged,
                 "ssen": parse_power_ssen, "nie": parse_power_nie}
