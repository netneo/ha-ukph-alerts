"""Constants for UK Prepper Hub Alerts."""

from datetime import timedelta
import logging

DOMAIN = "ukph_alerts"
NAME = "UK Prepper Hub Alerts"
VERSION = "0.4.0"
LOGGER = logging.getLogger(__package__)

USER_AGENT = f"UKPH-Alerts-HomeAssistant/{VERSION}"

CONF_REGION = "met_office_region"
CONF_RADIUS = "flood_radius_km"
CONF_SIDEBAR = "show_in_sidebar"
CONF_NOTIFY = "notify_services"
CONF_MIN_MET = "alert_min_met_office"
CONF_MIN_FLOOD = "alert_min_flood"
CONF_RIVER_ALERT = "alert_rivers"
CONF_ALL_CLEAR = "alert_all_clear"
CONF_ALERT_POWER = "alert_power_cuts"
CONF_ALERT_HEALTH = "alert_health"
CONF_ALERT_THREAT = "alert_threat_level"
CONF_ALERT_GRID = "alert_grid"
DEFAULT_ALERT_POWER = "near"
DEFAULT_ALERT_HEALTH = "amber"
DEFAULT_ALERT_THREAT = True
DEFAULT_ALERT_GRID = "high_risk"
POWER_ALERT_NEAR_KM = 2
DEFAULT_MIN_MET = "amber"
DEFAULT_MIN_FLOOD = "flood_warning"
DEFAULT_RIVER_ALERT = "very_high_rising"
DEFAULT_ALL_CLEAR = True
EVENT_NEW_WARNING = "ukph_alerts_new_warning"
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

# Representative points in each Met Office region, used only to pre-select the dropdown from HA's home location.
MET_OFFICE_REGION_POINTS = {
    "os": [(59.0, -3.0), (60.3, -1.3)],
    "he": [(57.5, -4.4), (57.9, -5.4), (58.3, -6.4), (56.8, -5.2)],
    "gr": [(57.15, -2.1), (57.4, -3.0), (57.6, -2.6)],
    "st": [(55.86, -4.25), (55.5, -4.6), (56.2, -5.5)],
    "ta": [(56.46, -2.97), (56.12, -3.94), (56.2, -3.2), (56.7, -3.5)],
    "dg": [(55.95, -3.19), (55.07, -3.6), (55.6, -2.8)],
    "ni": [(54.6, -5.93), (54.6, -6.7), (55.0, -7.3), (54.3, -7.6)],
    "wl": [(53.2, -4.1), (52.4, -4.0), (51.48, -3.18), (51.65, -3.94), (52.1, -3.4), (53.05, -3.0)],
    "nw": [(53.48, -2.24), (53.4, -2.98), (54.05, -2.8), (54.6, -3.1)],
    "ne": [(54.97, -1.61), (54.57, -1.23), (54.78, -1.57), (55.4, -1.7)],
    "yh": [(53.8, -1.55), (53.38, -1.47), (53.74, -0.33), (54.1, -1.0), (54.3, -0.5)],
    "wm": [(52.48, -1.9), (52.41, -1.51), (52.7, -2.75), (52.06, -2.7), (52.9, -2.1)],
    "em": [(52.95, -1.15), (52.64, -1.13), (53.23, -0.54), (52.92, -1.48), (52.25, -0.89)],
    "ee": [(52.2, 0.12), (52.63, 1.3), (52.06, 1.15), (51.75, 0.47), (52.13, -0.47), (51.8, -0.2)],
    "sw": [(51.86, -2.24), (50.72, -3.53), (50.37, -4.14), (51.45, -2.59), (50.72, -1.88), (51.06, -1.31), (50.26, -5.05)],
    "se": [(52.04, -0.76), (51.63, -0.75), (51.5, -0.12), (51.27, 1.08), (50.83, -0.14), (51.75, -1.26), (51.45, -0.97), (51.0, -0.9)],
}

PANEL_URL_PATH = "uk-prepper-hub"
PANEL_TITLE = "UK Prepper Hub"
PANEL_ICON = "mdi:shield-alert"
PANEL_COMPONENT = "ukph-alerts-panel"
STATIC_URL = "/ukph_alerts_static"

MET_OFFICE_URL = "https://www.metoffice.gov.uk/public/data/PWSCache/WarningsRSS/Region/{region}"
EA_FLOODS_URL = "https://environment.data.gov.uk/flood-monitoring/id/floods"
EA_STATIONS_URL = "https://environment.data.gov.uk/flood-monitoring/id/stations"
EA_MEASURE_READINGS_URL = "https://environment.data.gov.uk/flood-monitoring/id/measures/{measure}/readings"
EA_STATION_PAGE = "https://check-for-flooding.service.gov.uk/station/{rloi}"
SEPA_ARCGIS = "https://services-eu1.arcgis.com/jj6fR2HO7enbrICO/arcgis/rest/services"
SEPA_FLOOD_LAYERS = {  # layer -> default severity if the record's own text doesn't say
    "Flood_Warning_Areas_Point_(public)_view": 2,
    "Flood_Alert_Area_Point_view": 3,
}
SEPA_RIVERS_LAYER = "Water_Level_Stations_v2_VW"
SEPA_PAGE = "https://floodline.sepa.org.uk/live-flood-information/"
MI5_FEED = "https://www.mi5.gov.uk/UKThreatLevel/UKThreatLevel.xml"
MI5_PAGE = "https://www.mi5.gov.uk/threats-and-advice/threat-levels"
THREAT_LEVELS = ["low", "moderate", "substantial", "severe", "critical"]
ELEXON_SYSWARN = "https://data.elexon.co.uk/bmrs/api/v1/datasets/SYSWARN"
GRID_STATUSES = ["normal", "margin_notice", "high_risk", "demand_control"]
UKHSA_ALERTS = "https://ukhsa-dashboard.data.gov.uk/api/proxy/alerts/v1/{kind}/{code}"
UKHSA_PAGE = "https://ukhsa-dashboard.data.gov.uk/weather-health-alerts/{kind}"
HEALTH_LEVELS = ["green", "yellow", "amber", "red"]
UKHSA_REGION_NAMES = {
    "E12000001": "North East", "E12000002": "North West", "E12000003": "Yorkshire and The Humber",
    "E12000004": "East Midlands", "E12000005": "West Midlands", "E12000006": "East of England",
    "E12000007": "London", "E12000008": "South East", "E12000009": "South West",
}
UKHSA_REGION_POINTS = {
    "E12000001": [(54.97, -1.61), (54.57, -1.23), (55.4, -1.7), (54.78, -1.57)],
    "E12000002": [(53.48, -2.24), (53.4, -2.98), (54.05, -2.8), (54.6, -3.1), (53.2, -2.6)],
    "E12000003": [(53.8, -1.55), (53.38, -1.47), (53.74, -0.33), (54.1, -1.0), (54.3, -0.5)],
    "E12000004": [(52.95, -1.15), (52.64, -1.13), (53.23, -0.54), (52.25, -0.89), (52.92, -1.48)],
    "E12000005": [(52.48, -1.9), (52.41, -1.51), (52.7, -2.75), (52.06, -2.7), (52.9, -2.1)],
    "E12000006": [(52.2, 0.12), (52.63, 1.3), (52.06, 1.15), (51.75, 0.47), (52.13, -0.47), (51.8, -0.2)],
    "E12000007": [(51.5, -0.12), (51.55, -0.3), (51.45, 0.05), (51.42, -0.2), (51.58, 0.0)],
    "E12000008": [(51.27, 1.08), (50.83, -0.14), (51.75, -1.26), (51.45, -0.97), (51.0, -0.9),
                  (51.25, -0.6), (52.04, -0.76), (51.06, -1.31), (51.3, 0.5)],
    "E12000009": [(50.72, -3.53), (50.37, -4.14), (51.45, -2.59), (50.72, -1.88), (51.86, -2.24), (51.06, -2.5)],
}
# Which electricity networks serve each Met Office region (by HA's home location). SPEN and ENWL need keys
# and arrive later via the UKPH relay.
POWER_NETWORKS_BY_REGION = {
    "os": ["ssen"], "he": ["ssen"], "gr": ["ssen"], "ta": ["ssen"], "st": [], "dg": [],
    "ni": ["nie"], "wl": ["nged"], "nw": [], "ne": ["npg"], "yh": ["npg"], "wm": ["nged"],
    "em": ["nged"], "ee": ["ukpn"], "sw": ["nged", "ssen"], "se": ["ukpn", "ssen"], "UK": [],
}
POWER_NETWORK_NAMES = {"ukpn": "UK Power Networks", "nged": "National Grid Electricity Distribution",
                       "npg": "Northern Powergrid", "ssen": "SSEN", "nie": "NIE Networks"}
POWER_NETWORK_PAGES = {"ukpn": "https://www.ukpowernetworks.co.uk/power-cut/map",
                       "nged": "https://powercuts.nationalgrid.co.uk/",
                       "npg": "https://www.northernpowergrid.com/power-cuts",
                       "ssen": "https://powertrack.ssen.co.uk/", "nie": "https://powercheck.nienetworks.co.uk/"}
UKPN_FAULTS = "https://ukpowernetworks.opendatasoft.com/api/explore/v2.1/catalog/datasets/ukpn-live-faults/records"
NPG_FAULTS = "https://northernpowergrid.opendatasoft.com/api/explore/v2.1/catalog/datasets/live-power-cuts-data/records"
NGED_FAULTS = "https://connecteddata.nationalgrid.co.uk/api/3/action/datastore_search"
NGED_RESOURCE = "292f788f-4339-455b-8cc0-153e14509d4d"
SSEN_FAULTS = "https://ssen-powertrack-api.opcld.com/gridiview/reporter/info/livefaults"
NIE_FAULTS = "https://powercheck.nienetworks.co.uk/NIEPowerCheckerWebAPI/api/faults"
MAX_RIVER_STATIONS = 30
RIVER_FETCH_CONCURRENCY = 4
RIVER_TREND_THRESHOLD_M = 0.01
UKPH_API = "https://ukprepperhub.co.uk/wp-json/wp/v2"
UKPH_NEWS_CATEGORY_SLUG = "uk-prepper-daily-news"
UKPH_NEWS_CATEGORY_FALLBACK = 16
UKPH_UTM = {"utm_source": "homeassistant", "utm_medium": "integration"}

INTERVAL_MET_OFFICE = timedelta(minutes=10)
INTERVAL_FLOODS = timedelta(minutes=15)
INTERVAL_NEWS = timedelta(minutes=30)
INTERVAL_RIVERS = timedelta(minutes=15)
RIVER_STATION_REFRESH = timedelta(hours=24)
INTERVAL_NATIONAL = timedelta(minutes=15)
INTERVAL_POWER = timedelta(minutes=10)
INTERVAL_HEALTH = timedelta(minutes=60)

MET_OFFICE_LEVELS = ["none", "yellow", "amber", "red"]
# EA severityLevel -> enum state. 4 ("no longer in force") is not counted as active.
FLOOD_SEVERITIES = {1: "severe_flood_warning", 2: "flood_warning", 3: "flood_alert"}
FLOOD_LEVELS = ["none", "flood_alert", "flood_warning", "severe_flood_warning"]

ATTRIBUTION_MET_OFFICE = "Weather warnings from the Met Office (metoffice.gov.uk)"
ATTRIBUTION_EA = (
    "Flood warnings from the Environment Agency, under the Open Government Licence v3.0"
)
RIVER_STATUSES = ["low", "normal", "high", "very_high"]

ATTRIBUTION_POWER = "Power cut data from the electricity network operators"
ATTRIBUTION_UKHSA = "Weather-health alerts from the UK Health Security Agency (experimental source)"
ATTRIBUTION_MI5 = "Threat level from MI5 (mi5.gov.uk)"
ATTRIBUTION_GRID = "Grid notices from NESO via Elexon (Insights Solution)"
ATTRIBUTION_SEPA = "Flood and river data from SEPA (sepa.org.uk)"

ATTRIBUTION_UKPH = "News from UK Prepper Hub (ukprepperhub.co.uk)"
