// UK Prepper Hub sidebar page. Plain web component (no build step); reads the integration's own sensors.

const LEVEL_COLOURS = {
  red: "#d32f2f", amber: "#f57c00", yellow: "#fbc02d",
  severe_flood_warning: "#d32f2f", flood_warning: "#f57c00", flood_alert: "#fbc02d",
};
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
    const keys = ["met_office_warnings", "met_office_highest_level", "flood_warnings", "flood_highest_severity", "daily_news"];
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

  _badge(label, state) {
    const colour = LEVEL_COLOURS[state];
    const text = LEVEL_LABELS[state] || "Unavailable";
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
      </div>
      <div class="card">
        <h2>Met Office warnings${region ? `: ${esc(region)}` : ""}</h2>
        ${moHtml}
        <h2>Flood warnings${radius ? ` within ${esc(Math.round(radius))} km` : ""}</h2>
        ${flHtml}
        <div class="footer">
          <a href="${settings}">Change region or radius</a>
          <span>${esc(mo?.attributes?.attribution || "")}${fl?.attributes?.attribution ? ` · ${esc(fl.attributes.attribution)}` : ""}</span>
        </div>
      </div>`;
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
  .badges { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
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
