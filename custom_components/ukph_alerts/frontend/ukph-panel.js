// UK Prepper Hub sidebar page. Plain web component (no build step); reads the integration's own sensors.

const LEVEL_COLOURS = {
  red: "#d32f2f", amber: "#f57c00", yellow: "#fbc02d",
  severe_flood_warning: "#d32f2f", flood_warning: "#f57c00", flood_alert: "#fbc02d",
};
const RIVER_COLOURS = { very_high: "#d32f2f", high: "#f57c00", normal: "#43a047", low: "#1e88e5" };
const RIVER_LABELS = { very_high: "Very high", high: "High", normal: "Normal", low: "Low" };
const TREND_ARROWS = { rising: "▲", falling: "▼", steady: "▶" };
const LEVEL_LABELS = {
  none: "None", yellow: "Yellow", amber: "Amber", red: "Red",
  flood_alert: "Flood alert", flood_warning: "Flood warning", severe_flood_warning: "Severe flood warning",
};

const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? esc(u) : "");
const link = (url, text) => (safeUrl(url) ? `<a href="${safeUrl(url)}" target="_blank" rel="noopener">${esc(text)}</a>` : esc(text));

class UkphAlertsPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    this._render();
  }
  set panel(panel) {
    this._panel = panel;
    this._render();
  }
  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menu) this._menu.narrow = narrow;
  }

  _entity(key) {
    const id = this._panel?.config?.entities?.[key];
    return id ? this._hass.states[id] : undefined;
  }

  _fmt(value, opts) {
    if (!value) return "";
    const d = new Date(value);
    if (isNaN(d)) return esc(value);
    return d.toLocaleString("en-GB", { timeZone: this._hass.config.time_zone, ...opts });
  }

  _render() {
    if (!this._hass || !this._panel) return;
    const keys = ["met_office_warnings", "met_office_highest_level", "flood_warnings", "flood_highest_severity", "rivers_above_normal", "daily_news"];
    // hass updates many times a second; only redraw when one of our sensors actually changed.
    const sig = keys.map((k) => this._entity(k)?.last_updated).join("|") + this._hass.themes?.darkMode;
    if (sig === this._sig) return;
    this._sig = sig;

    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.shadowRoot.innerHTML = `<style>${STYLE}</style>
        <div class="toolbar"><span class="menu"></span><div class="title">UK Prepper Hub</div></div>
        <div class="content"></div>`;
      this._menu = document.createElement("ha-menu-button");
      this.shadowRoot.querySelector(".menu").appendChild(this._menu);
    }
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    this.shadowRoot.querySelector(".content").innerHTML = `
      <div class="col">${this._warnings()}</div>
      <div class="col">${this._news()}</div>`;
  }

  _badge(label, state, override) {
    const colour = override ? override.colour : LEVEL_COLOURS[state];
    const text = override ? override.text : LEVEL_LABELS[state] || "Unavailable";
    return `<div class="badge ${colour ? "active" : ""}" style="${colour ? `--level:${colour}` : ""}">
      <div class="badge-label">${esc(label)}</div><div class="badge-state">${esc(text)}</div></div>`;
  }

  _unavailable(e) {
    return !e || e.state === "unavailable" || e.state === "unknown";
  }

  _warnings() {
    const mo = this._entity("met_office_warnings");
    const moLevel = this._entity("met_office_highest_level");
    const fl = this._entity("flood_warnings");
    const flLevel = this._entity("flood_highest_severity");
    const settings = `/config/integrations/integration/ukph_alerts`;

    let moHtml;
    if (this._unavailable(mo)) {
      moHtml = `<p class="muted">Couldn't reach the Met Office. It will retry automatically.</p>`;
    } else if (!(mo.attributes.warnings || []).length) {
      moHtml = `<p class="ok">No weather warnings in force.</p>`;
    } else {
      moHtml = mo.attributes.warnings.map((w) => `
        <div class="item" style="--level:${LEVEL_COLOURS[w.level] || "var(--divider-color)"}">
          <div class="item-title">${esc((w.level || "").replace(/^./, (c) => c.toUpperCase()))} warning: ${esc(w.hazard || w.title)}</div>
          ${w.valid_from && w.valid_to ? `<div class="meta">${this._fmt(w.valid_from, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })} to ${this._fmt(w.valid_to, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</div>` : ""}
          ${(w.areas || []).length ? `<div class="meta">${esc(w.areas.join(", "))}</div>` : ""}
          ${w.link ? `<div class="meta">${link(w.link, "Full details on the Met Office site")}</div>` : ""}
        </div>`).join("");
    }

    let flHtml;
    if (this._unavailable(fl)) {
      flHtml = `<p class="muted">Couldn't reach the Environment Agency. It will retry automatically.</p>`;
    } else if (!(fl.attributes.warnings || []).length) {
      flHtml = `<p class="ok">No flood alerts or warnings nearby.</p>`;
    } else {
      flHtml = fl.attributes.warnings.map((w) => `
        <div class="item" style="--level:${LEVEL_COLOURS[w.severity] || "var(--divider-color)"}">
          <div class="item-title">${esc(LEVEL_LABELS[w.severity] || w.severity)}: ${esc(w.description)}</div>
          ${w.river_or_sea ? `<div class="meta">${esc(w.river_or_sea)}</div>` : ""}
          ${w.message ? `<div class="meta msg">${esc(w.message)}</div>` : ""}
          ${w.link ? `<div class="meta">${link(w.link, "Full details on GOV.UK")}</div>` : ""}
        </div>`).join("");
    }

    const region = mo?.attributes?.region || "";
    const radius = fl?.attributes?.radius_km;
    return `
      <div class="badges">
        ${this._badge("Met Office", moLevel?.state)}
        ${this._badge("Floods nearby", flLevel?.state)}
        ${this._badge("Rivers", null, this._riverBadge())}
      </div>
      <div class="card">
        <h2>Met Office warnings${region ? `: ${esc(region)}` : ""}</h2>
        ${moHtml}
        <h2>Flood warnings${radius ? ` within ${esc(Math.round(radius))} km` : ""}</h2>
        ${flHtml}
        ${this._rivers()}
        <div class="footer">
          <a href="${settings}">Change region, radius or alerts</a>
          <span>${esc(mo?.attributes?.attribution || "")}${fl?.attributes?.attribution ? ` · ${esc(fl.attributes.attribution)}` : ""}</span>
        </div>
      </div>`;
  }

  _riverBadge() {
    const r = this._entity("rivers_above_normal");
    if (this._unavailable(r)) return { text: "Unavailable" };
    const high = r.attributes.rivers_above_normal || [];
    if (!high.length) return { text: "All normal" };
    const worst = high.some((s) => s.status === "very_high") ? "very_high" : "high";
    return { text: `${high.length} ${worst === "very_high" ? "very high" : "high"}`, colour: RIVER_COLOURS[worst] };
  }

  _rivers() {
    const r = this._entity("rivers_above_normal");
    const radius = r?.attributes?.radius_km;
    const title = `<h2>River levels${radius ? ` within ${esc(Math.round(radius))} km` : ""}</h2>`;
    if (this._unavailable(r)) return `${title}<p class="muted">Couldn't reach the Environment Agency. It will retry automatically.</p>`;
    const stations = [...(r.attributes.stations || [])];
    if (!stations.length) return `${title}<p class="ok">No river level stations within this distance.</p>`;
    const order = { very_high: 0, high: 1 };
    stations.sort((a, b) => (order[a.status] ?? 2) - (order[b.status] ?? 2) || a.distance_km - b.distance_km);
    const rows = stations.map((s) => {
      if (s.level == null) {
        return `<div class="river"><div class="river-head"><span>${link(s.link, `${s.river} at ${s.station}`)}</span><span class="muted">No recent reading</span></div></div>`;
      }
      const top = Math.max(s.highest_recent ?? s.typical_high, s.typical_high, s.level);
      const bottom = Math.min(s.typical_low, s.level);
      const span = (top - bottom) * 1.1 || 1;
      const pos = (v) => Math.max(0, Math.min(100, ((v - bottom) / span) * 100 + 4));
      const colour = RIVER_COLOURS[s.status] || "var(--secondary-text-color)";
      const change = s.change_1h_m == null ? "" : ` (${s.change_1h_m > 0 ? "+" : ""}${Math.round(s.change_1h_m * 1000)} mm/h)`;
      return `<div class="river" style="--level:${colour}">
        <div class="river-head">
          <span>${link(s.link, `${s.river} at ${s.station}`)} <span class="meta">${esc(s.distance_km)} km</span></span>
          <span class="river-state">${esc(Number(s.level).toFixed(2))} m <span class="arrow">${TREND_ARROWS[s.trend] || ""}</span> ${esc(RIVER_LABELS[s.status] || "")}</span>
        </div>
        <div class="bar"><div class="band" style="left:${pos(s.typical_low)}%;width:${pos(s.typical_high) - pos(s.typical_low)}%"></div><div class="marker" style="left:${pos(s.level)}%"></div></div>
        <div class="meta">Normal ${esc(s.typical_low.toFixed(2))}–${esc(s.typical_high.toFixed(2))} m · ${esc(s.trend || "trend unknown")}${esc(change)}</div>
      </div>`;
    }).join("");
    const shown = r.attributes.stations_shown, total = r.attributes.stations_in_radius;
    const capped = total > shown ? `<p class="meta">Showing the nearest ${esc(shown)} of ${esc(total)} stations.</p>` : "";
    return `${title}${rows}${capped}`;
  }

  _news() {
    const n = this._entity("daily_news");
    if (this._unavailable(n)) {
      return `<div class="card"><h2>UK Prepper Hub daily news</h2><p class="muted">Couldn't reach UK Prepper Hub. It will retry automatically.</p></div>`;
    }
    const a = n.attributes;
    const stories = a.stories || [];
    const sections = [...new Set(stories.map((s) => s.section))];
    const storyHtml = sections.map((sec) => `
      <h3>${esc(sec)}</h3>
      <ul>${stories.filter((s) => s.section === sec).map((s) => `
        <li>${link(s.url, (s.location ? s.location + ": " : "") + s.headline)}${s.status && s.status !== "Confirmed" ? ` <span class="status">${esc(s.status)}</span>` : ""}</li>`).join("")}
      </ul>`).join("");
    return `
      <div class="card news">
        <div class="eyebrow">UK Prepper Hub daily news</div>
        <h1>${link(a.link, n.state)}</h1>
        <p>${esc(a.brief)}</p>
        <div class="meta">Published ${this._fmt(a.published, { hour: "2-digit", minute: "2-digit", weekday: "short", day: "numeric", month: "short" })}${stories.length ? ` · ${stories.length} stories` : ""}</div>
      </div>
      ${stories.length ? `<div class="card stories">${storyHtml}</div>` : ""}
      <div class="credit">${esc(a.attribution || "")}</div>`;
  }
}

const STYLE = `
  :host { display: block; min-height: 100vh; background: var(--primary-background-color); color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
  .toolbar { display: flex; align-items: center; height: var(--header-height, 56px); padding: 0 12px;
    background: var(--app-header-background-color, var(--primary-background-color));
    color: var(--app-header-text-color, var(--primary-text-color));
    border-bottom: var(--app-header-border-bottom, 1px solid var(--divider-color)); box-sizing: border-box; }
  .title { font-size: 20px; margin-left: 12px; }
  .content { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; padding: 16px;
    max-width: 1200px; margin: 0 auto; box-sizing: border-box; }
  .col { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .card { background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 12px);
    border: 1px solid var(--ha-card-border-color, var(--divider-color)); box-shadow: var(--ha-card-box-shadow, none);
    padding: 16px 20px; }
  h1 { font-size: 22px; line-height: 1.3; margin: 4px 0 12px; }
  h2 { font-size: 17px; margin: 4px 0 10px; }
  h2:not(:first-child) { margin-top: 20px; }
  h3 { font-size: 15px; margin: 16px 0 6px; }
  h3:first-child { margin-top: 0; }
  p { line-height: 1.55; margin: 0 0 10px; }
  ul { margin: 0; padding-left: 20px; }
  li { margin: 4px 0; line-height: 1.45; }
  a { color: var(--primary-color); }
  .eyebrow { font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: var(--secondary-text-color); }
  .meta { font-size: 13px; color: var(--secondary-text-color); margin-top: 3px; }
  .msg { white-space: pre-line; }
  .muted { color: var(--secondary-text-color); }
  .ok { color: var(--secondary-text-color); }
  .status { font-size: 12px; font-style: italic; color: var(--secondary-text-color); }
  .badges { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; }
  .river { margin: 10px 0 14px; }
  .river-head { display: flex; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
  .river-state { font-weight: 500; color: var(--level); white-space: nowrap; }
  .arrow { font-size: 11px; }
  .bar { position: relative; height: 8px; border-radius: 4px; background: var(--divider-color); margin: 6px 0 4px; }
  .band { position: absolute; top: 0; bottom: 0; border-radius: 4px; background: rgba(67, 160, 71, 0.35); }
  .marker { position: absolute; top: -3px; width: 4px; height: 14px; margin-left: -2px; border-radius: 2px; background: var(--level); }
  .badge { background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 12px);
    border: 1px solid var(--ha-card-border-color, var(--divider-color)); padding: 12px 16px; }
  .badge.active { border-left: 6px solid var(--level); }
  .badge-label { font-size: 13px; color: var(--secondary-text-color); }
  .badge-state { font-size: 18px; font-weight: 500; margin-top: 2px; }
  .badge.active .badge-state { color: var(--level); }
  .item { border-left: 4px solid var(--level); padding: 4px 0 4px 12px; margin: 8px 0 12px; }
  .item-title { font-weight: 500; }
  .footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; margin-top: 16px; padding-top: 12px;
    border-top: 1px solid var(--divider-color); font-size: 12px; color: var(--secondary-text-color); }
  .credit { font-size: 12px; color: var(--secondary-text-color); padding: 0 4px; }
`;

if (!customElements.get("ukph-alerts-panel")) customElements.define("ukph-alerts-panel", UkphAlertsPanel);
