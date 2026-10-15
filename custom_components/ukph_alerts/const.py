"""Constants for UK Prepper Hub Alerts."""

from datetime import timedelta
import logging

DOMAIN = "ukph_alerts"
NAME = "UK Prepper Hub Alerts"
VERSION = "0.1.0"
LOGGER = logging.getLogger(__package__)

USER_AGENT = f"UKPH-Alerts-HomeAssistant/{VERSION}"

CONF_REGION = "met_office_region"
CONF_RADIUS = "flood_radius_km"
DEFAULT_RADIUS = 10
MIN_RADIUS = 1
MAX_RADIUS = 50

# Met Office warning feed region codes, as listed at weather.metoffice.gov.uk/guides/rss
MET_OFFICE_REGIONS = {
    "UK": "Whole UK",
    "os": "Orkney & Shetland",
    "he": "Highlands & Eilean Siar",
    "gr": "Grampian",
    "st": "Strathclyde",
    "ta": "Central, Tayside & Fife",
    "dg": "SW Scotland, Lothian Borders",
    "ni": "Northern Ireland",
    "wl": "Wales",
    "nw": "North West England",
    "ne": "North East England",
    "yh": "Yorkshire & Humber",
    "wm": "West Midlands",
    "em": "East Midlands",
    "ee": "East of England",
    "sw": "South West England",
    "se": "London & South East England",
}

MET_OFFICE_URL = "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/{region}"
EA_FLOODS_URL = "https://environment.data.gov.uk/flood-monitoring/id/floods"
UKPH_API = "https://ukprepperhub.co.uk/wp-json/wp/v2"
UKPH_NEWS_CATEGORY_SLUG = "uk-prepper-daily-news"
UKPH_NEWS_CATEGORY_FALLBACK = 16
UKPH_UTM = {"utm_source": "homeassistant", "utm_medium": "integration"}

INTERVAL_MET_OFFICE = timedelta(minutes=10)
INTERVAL_FLOODS = timedelta(minutes=15)
INTERVAL_NEWS = timedelta(minutes=30)

MET_OFFICE_LEVELS = ["none", "yellow", "amber", "red"]
# EA severityLevel -> enum state. 4 ("no longer in force") is not counted as active.
FLOOD_SEVERITIES = {1: "severe_flood_warning", 2: "flood_warning", 3: "flood_alert"}
FLOOD_LEVELS = ["none", "flood_alert", "flood_warning", "severe_flood_warning"]

ATTRIBUTION_MET_OFFICE = "Weather warnings from the Met Office (metoffice.gov.uk)"
ATTRIBUTION_EA = (
    "Flood warnings from the Environment Agency, under the Open Government Licence v3.0"
)
ATTRIBUTION_UKPH = "News from UK Prepper Hub (ukprepperhub.co.uk)"
