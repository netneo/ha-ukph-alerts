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
