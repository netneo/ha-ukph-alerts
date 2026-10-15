# UK Prepper Hub Alerts

A Home Assistant integration that brings UK hazard alerts and UK Prepper Hub's daily news into one place:

- **Met Office severe weather warnings** for your region (whole UK or any of the 16 Met Office regions)
- **Environment Agency flood warnings** near your home (England only)
- **UK Prepper Hub Daily News**: today's headline, the Quick News Brief, and every story with a link

All of these are normal Home Assistant sensors, so you can show them on a dashboard or use them in automations, such as a phone alert when an amber warning or a flood warning is issued near you.

## Installation (HACS)

1. In HACS, open the ⋮ menu and choose **Custom repositories**. Add `https://github.com/netneo/ha-ukph-alerts` with type **Integration**.
2. Search for **UK Prepper Hub Alerts**, install it, and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → UK Prepper Hub Alerts**.
4. Pick your Met Office region and a flood search radius. You can change both later with **Configure**.

## Sensors

| Sensor | State | Attributes |
|---|---|---|
| Met Office warnings | Number of warnings in force | `highest_level`, `region`, `warnings` (level, hazard, areas, valid_from, valid_to, link) |
| Met Office highest warning | `none` / `yellow` / `amber` / `red` | |
| Flood warnings nearby | Number of active flood alerts/warnings | `highest_severity`, `radius_km`, `warnings` (severity, description, county, river_or_sea, message, link) |
| Flood highest severity | `none` / `flood_alert` / `flood_warning` / `severe_flood_warning` | |
| Daily news | Title of today's post | `link`, `published`, `brief`, `story_count`, `stories` (section, location, headline, status, url) |

How often each source is checked: Met Office every 10 minutes, Environment Agency every 15 minutes, UK Prepper Hub every 30 minutes.

## Example: news card

```yaml
type: markdown
content: >
  **[{{ states('sensor.uk_prepper_hub_alerts_daily_news') }}]({{ state_attr('sensor.uk_prepper_hub_alerts_daily_news', 'link') }})**

  {{ state_attr('sensor.uk_prepper_hub_alerts_daily_news', 'brief') }}
```

## Example: automation

```yaml
triggers:
  - trigger: state
    entity_id: sensor.uk_prepper_hub_alerts_met_office_highest_warning
    to: [amber, red]
actions:
  - action: notify.notify
    data:
      message: >
        Met Office {{ trigger.to_state.state }} warning in force for your region.
```

## Privacy

- Flood warnings use the home location set in Home Assistant, **rounded to about 1 km**, and send it only to the Environment Agency's API.
- Your location is never stored by this integration and never sent to UK Prepper Hub or the Met Office.

## Data sources and attribution

- Weather warnings © Crown copyright, from the [Met Office](https://www.metoffice.gov.uk/weather/warnings-and-advice/uk-warnings).
- Flood warnings from the [Environment Agency](https://check-for-flooding.service.gov.uk/), used under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). This data covers England only.
- News from [UK Prepper Hub](https://ukprepperhub.co.uk/).

This integration is not affiliated with or endorsed by the Met Office or the Environment Agency.
