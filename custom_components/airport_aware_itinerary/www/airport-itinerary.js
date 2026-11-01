const DOMAIN = "airport_aware_itinerary";
const DEFAULT_ENTITY = "sensor.flight_itineraries";
const CARD_VERSION = "1.6.14";

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]
  );

const stamp = (value) => {
  if (typeof value === "number") return value > 0 ? value * 1000 : null;
  if (typeof value !== "string" || !value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
};

// HA timestamps can arrive slightly ahead of the browser clock. Keep the
// five-minute age limit, but tolerate up to one minute of positive clock skew.
const isFreshUpdate = (updatedAt, now) => updatedAt != null
  && now - updatedAt >= -60000 && now - updatedAt <= 300000;

// FR24's real arrival is landing evidence, not confirmation at the gate.
// finished_at is retained for compatibility with older integration versions.
const arrivalState = (leg, tracked, now) => {
  const observed = (...values) => values.map(stamp).find((value) => value != null && value <= now + 60000) ?? null;
  const evidence = leg.evidence || {};
  const gateAt = observed(evidence.gate_arrival, leg.final_arrival_at, tracked?.time_gate_arrival, tracked?.gate_arrival);
  const landedAt = observed(evidence.touchdown, evidence.actual_arrival, tracked?.time_real_landing,
    tracked?.landing, tracked?.time_real_arrival, leg.finished_at, tracked?.finished_at);
  const fresh = isFreshUpdate(stamp(tracked?.position_updated_at), now);
  const arrived = gateAt != null || (fresh && tracked?.gate_arrived_sent === true);
  const completedAt = observed(evidence.manual_completion, evidence.inferred_completion);
  const landed = !arrived && !leg.completed && completedAt == null
    && (landedAt != null || (fresh && tracked?.has_landed === true));
  return { gateAt, landedAt, arrived, landed, completedAt,
    finalAt: gateAt || completedAt,
    taxiing: landed && fresh && tracked?.is_live === true && tracked?.on_ground === true
      && Number.isFinite(tracked?.ground_speed) && tracked.ground_speed > 0 };
};

const duration = (seconds) => {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  const minutes = Math.floor(seconds / 60);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const remainder = minutes % 60;
  if (days) return `${days}d ${hours}h ${remainder}m`;
  if (hours) return `${hours}h ${remainder}m`;
  return `${remainder}m`;
};

const retainedJourneyTiming = (trip, tracked, now) => {
  const legs = trip?.legs || [];
  if (!legs.length) return null;
  const first = legs[0], last = legs.at(-1);
  const match = (leg) => tracked.find((row) => row.itinerary_id === trip.id && row.leg_id === leg.id);
  const arrival = arrivalState(last, match(last), now);
  if (!arrival.arrived && !arrival.landed && !last.completed && arrival.completedAt == null) return null;
  const start = stamp(first.evidence?.departure) ?? stamp(match(first)?.time_real_departure);
  const end = arrival.arrived ? arrival.gateAt : arrival.landedAt;
  const elapsed = start != null && end != null && end >= start ? duration((end - start) / 1000) : "Unavailable";
  return {
    label: arrival.arrived ? "Actual travel time" : arrival.landed ? "Departure to landing" : "Actual travel time",
    elapsed,
    status: arrival.arrived ? "Final arrival · at gate" : arrival.landed ? "Landed · awaiting gate" : "Completed",
    note: arrival.arrived ? "Actual time from first departure to final gate arrival, retained from tracking."
      : arrival.landed ? "Actual time from first departure to landing; final gate arrival is not yet confirmed."
        : "Journey marked completed; actual duration requires recorded departure and arrival times.",
  };
};

const localTime = (date, timezone, options = {}, locale) => {
  if (!date || !timezone) return "Time unavailable";
  try {
    return new Intl.DateTimeFormat(locale || undefined, {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      ...(options.date ? { weekday: "short", month: "short", day: "numeric" } : {}),
      ...(options.zone ? { timeZoneName: "short" } : {}),
    }).format(date);
  } catch {
    return "Time unavailable";
  }
};

const currentAirportTime = (timezone, locale) => {
  if (!timezone) return "Airport time unavailable";
  try {
    return new Intl.DateTimeFormat(locale || undefined, {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      timeZoneName: "short",
    }).format(new Date());
  } catch {
    return "Airport time unavailable";
  }
};

// Order trips by earliest scheduled departure first; keep undated drafts last.
const sortItineraries = (trips) => {
  const firstDeparture = (trip) => {
    const dates = (trip.legs || []).map((leg) => stamp(leg.departure?.utc_timestamp)).filter((date) => date != null);
    return dates.length ? Math.min(...dates) : Infinity;
  };
  return [...trips].sort((a, b) => {
    const left = firstDeparture(a), right = firstDeparture(b);
    return left === right ? String(a.id).localeCompare(String(b.id)) : left < right ? -1 : 1;
  });
};

// Selection follows journey timing independently of the dropdown's date order.
const preferredItinerary = (trips, journeys, now, finishDelaySeconds = 300) => {
  const candidates = [];
  for (const trip of trips) {
    const groups = (journeys || []).filter((journey) => journey.itinerary_id === trip.id);
    const timing = groups.length ? groups : (trip.legs || []).map((leg) => ({
      leg_ids: [leg.id],
      departure_at: leg.departure?.utc_timestamp,
      expires_at: leg.arrival?.utc_timestamp,
      completed: Boolean(leg.completed || arrivalState(leg, null, now).arrived),
      final_arrival_at: leg.evidence?.gate_arrival || leg.final_arrival_at,
      arrival_pending: arrivalState(leg, null, now).landed,
    }));
    for (const journey of timing) {
      const journeyLegs = (trip.legs || []).filter((leg) => !journey.leg_ids || journey.leg_ids.includes(leg.id))
        .sort((a, b) => (stamp(a.departure?.utc_timestamp) || 0) - (stamp(b.departure?.utc_timestamp) || 0));
      // Older integrations already retain gate evidence on the leg, even when
      // the journey does not yet expose final_arrival_at.
      const gateAt = stamp(journey.final_arrival_at) ?? arrivalState(journeyLegs.at(-1) || {}, null, now).gateAt;
      const retainUntil = gateAt != null ? Math.max(gateAt + finishDelaySeconds * 1000, stamp(journey.api_stop_at) || 0) : null;
      const retainingArrival = retainUntil != null && now < retainUntil;
      if (!journey.airborne && !retainingArrival && (journey.completed || ["completed", "expired"].includes(journey.status))) continue;
      const departure = stamp(journey.departure_at);
      if (departure == null) continue;
      const end = stamp(journey.expires_at) ?? stamp(journey.arrival_at) ?? departure + 48 * 3600 * 1000;
      const active = journey.airborne || retainingArrival || (departure <= now && (now < end
        || journey.arrival_pending && now < departure + 48 * 3600 * 1000));
      if (active || departure > now) candidates.push({ trip, active: Boolean(active), departure });
    }
  }
  candidates.sort((a, b) => Number(b.active) - Number(a.active) || a.departure - b.departure || String(a.trip.id).localeCompare(String(b.trip.id)));
  return candidates[0]?.trip ?? trips[0];
};

const normalizedFlightNumber = (value) => String(value || "").toUpperCase().replace(/[^A-Z0-9]/g, "")
  .replace(/^([A-Z]{2,3}|[A-Z]\d|\d[A-Z])0*(\d+)([A-Z]?)$/, (_, prefix, digits, suffix) => prefix + Number(digits) + suffix);

// A number-only watch is acknowledgement, not evidence of a dated occurrence.
const waitingForFlightDetails = (legs, flights) => Array.isArray(flights) && legs.some((leg) =>
  !leg.completed && !leg.finished_at && flights.some((flight) => flight && flight.tracked_type === "schedule"
    && !stamp(flight.time_scheduled_departure)
    && [flight.flight_number, flight.callsign].some((value) => normalizedFlightNumber(value) === normalizedFlightNumber(leg.flight_number))
    && [[leg.origin_airport, flight.airport_origin_code_iata], [leg.destination_airport, flight.airport_destination_code_iata]]
      .every(([saved, reported]) => !saved || !reported || saved.toUpperCase() === reported.toUpperCase())));

const formatClock = (value, timezone, locale) => {
  const ms = stamp(value);
  return ms && timezone ? localTime(new Date(ms), timezone, { date: true, zone: true }, locale) : "Not scheduled";
};

const airportTime = (value, timezone, locale) => {
  const ms = stamp(value);
  if (!ms || !timezone) return "—";
  try {
    return new Intl.DateTimeFormat(locale || undefined, {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(ms));
  } catch {
    return "—";
  }
};

const airportDate = (value, timezone, locale) => {
  const ms = stamp(value);
  if (!ms || !timezone) return "Date unavailable";
  try {
    return new Intl.DateTimeFormat(locale || undefined, {
      timeZone: timezone,
      weekday: "short",
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(new Date(ms));
  } catch {
    return "Date unavailable";
  }
};

const airportZoneName = (value, timezone, locale) => {
  const ms = stamp(value);
  if (!ms || !timezone) return timezone || "Timezone unavailable";
  try {
    return new Intl.DateTimeFormat(locale || undefined, {
      timeZone: timezone,
      timeZoneName: "short",
    }).formatToParts(new Date(ms)).find((part) => part.type === "timeZoneName")?.value ?? timezone;
  } catch {
    return timezone;
  }
};

const routeProgress = (origin, destination, position) => {
  const points = [origin, destination, position];
  if (points.some((point) => !point || !Number.isFinite(Number(point.latitude)) || !Number.isFinite(Number(point.longitude)))) return null;
  const [start, end, current] = points.map((point) => ({
    latitude: Number(point.latitude),
    longitude: Number(point.longitude),
  }));
  if (points.some((point) => Number(point.latitude) < -90 || Number(point.latitude) > 90 || Number(point.longitude) < -180 || Number(point.longitude) > 180)) return null;
  const radians = (degrees) => degrees * Math.PI / 180;
  const angularDistance = (a, b) => {
    const lat1 = radians(a.latitude);
    const lat2 = radians(b.latitude);
    const deltaLat = lat2 - lat1;
    const deltaLon = radians(b.longitude - a.longitude);
    const value = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLon / 2) ** 2;
    return 2 * Math.atan2(Math.sqrt(value), Math.sqrt(Math.max(0, 1 - value)));
  };
  const initialBearing = (a, b) => {
    const lat1 = radians(a.latitude);
    const lat2 = radians(b.latitude);
    const deltaLon = radians(b.longitude - a.longitude);
    return Math.atan2(
      Math.sin(deltaLon) * Math.cos(lat2),
      Math.cos(lat1) * Math.sin(lat2) - Math.sin(lat1) * Math.cos(lat2) * Math.cos(deltaLon),
    );
  };
  const total = angularDistance(start, end);
  if (!Number.isFinite(total) || total < 1e-8) return null;
  const fromStart = angularDistance(start, current);
  const bearingDelta = initialBearing(start, current) - initialBearing(start, end);
  const alongTrack = Math.atan2(
    Math.sin(fromStart) * Math.cos(bearingDelta),
    Math.cos(fromStart),
  );
  return Math.min(100, Math.max(0, alongTrack / total * 100));
};

const responseData = (result) => result?.response ?? result?.service_response ?? result ?? {};
const STATUS_COLOR_CONFIG = {
  scheduled: "--airport-itinerary-status-scheduled",
  in_transit: "--airport-itinerary-status-in-transit",
  airborne: "--airport-itinerary-status-airborne",
  landed: "--airport-itinerary-status-landed",
  arrived: "--airport-itinerary-status-arrived",
  connection: "--airport-itinerary-status-connection",
  completed: "--airport-itinerary-status-completed",
};

class AirportItineraryBase extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._config = {};
    this._message = "";
    this._messageType = "error";
    this._timer = null;
    this._skipPreserve = false;
    this._pendingRender = false;
    this.shadowRoot.addEventListener("focusout", () => {
      window.setTimeout(() => {
        if (this._pendingRender && !this.shouldDeferRender()) this.requestRender();
      }, 0);
    });
  }

  setConfig(config) {
    this._config = { entity: DEFAULT_ENTITY, ...config };
    const configuredStyles = {
      header_background: "--airport-itinerary-header-background",
      progress_color: "--airport-itinerary-progress-color",
      finished_color: "--airport-itinerary-finished-color",
    };
    for (const [key, property] of Object.entries(configuredStyles)) {
      if (typeof config[key] === "string" && config[key].trim()) {
        this.style.setProperty(property, config[key].trim());
      } else {
        this.style.removeProperty(property);
      }
    }
    const opacityValue = config.header_background_opacity;
    const opacityMatch = typeof opacityValue === "number"
      ? String(opacityValue).match(/^(\d+(?:\.\d+)?)$/)
      : typeof opacityValue === "string" ? opacityValue.trim().match(/^(\d+(?:\.\d+)?)%?$/) : null;
    if (opacityMatch) {
      const opacity = Math.min(100, Math.max(0, Number(opacityMatch[1])));
      this.style.setProperty("--airport-itinerary-header-background-opacity", `${opacity}%`);
    } else {
      this.style.removeProperty("--airport-itinerary-header-background-opacity");
    }
    for (const [key, property] of Object.entries(STATUS_COLOR_CONFIG)) {
      const value = config.status_colors?.[key];
      if (typeof value === "string" && value.trim()) this.style.setProperty(property, value.trim());
      else this.style.removeProperty(property);
    }
    this.render();
  }

  set hass(value) {
    this._hass = value;
    if (this.shouldRenderForHassChange()) this.requestRender();
  }

  get hass() {
    return this._hass;
  }

  get displayLocale() {
    return this._hass?.locale?.language || this._hass?.language || navigator.language;
  }

  shouldRenderForHassChange() {
    return true;
  }

  shouldDeferRender() {
    return false;
  }

  requestRender() {
    if (this.shouldDeferRender()) {
      this._pendingRender = true;
      return;
    }
    this._pendingRender = false;
    this.render();
  }

  get refreshInterval() {
    return 30000;
  }

  connectedCallback() {
    if (this.refreshInterval) {
      this._timer = window.setInterval(() => this.requestRender(), this.refreshInterval);
    }
  }

  disconnectedCallback() {
    if (this._timer) window.clearInterval(this._timer);
  }

  get model() {
    const states = Object.values(this._hass?.states ?? {});
    const configured = this._hass?.states?.[this._config.entity];
    const state = Array.isArray(configured?.attributes?.itineraries)
      ? configured
      : states.find((candidate) =>
        candidate.entity_id?.startsWith("sensor.")
        && Array.isArray(candidate.attributes?.itineraries)
      ) ?? configured;
    return {
      state,
      itineraries: sortItineraries(Array.isArray(state?.attributes?.itineraries) ? state.attributes.itineraries : []),
      tracked: Array.isArray(state?.attributes?.tracked_legs) ? state.attributes.tracked_legs : [],
    };
  }

  get servicesAvailable() {
    const services = this._hass?.services?.[DOMAIN];
    return Boolean(services?.create_itinerary && services?.add_flight);
  }

  async call(service, data) {
    if (!this._hass) throw new Error("Home Assistant is not ready.");
    const result = await this._hass.callService(DOMAIN, service, data, undefined, false, true);
    const response = responseData(result);
    if (response.success === false) throw new Error(response.error || "The action was not completed.");
    return response;
  }

  styles() {
    return `
      :host {
        display:block;
        container-type:inline-size;
        color:var(--primary-text-color);
        --airport-itinerary-header-background:transparent;
        --airport-itinerary-header-background-opacity:100%;
        --airport-itinerary-status-scheduled:var(--primary-text-color);
        --airport-itinerary-status-in-transit:var(--state-active-color,var(--primary-color));
        --airport-itinerary-status-airborne:var(--info-color);
        --airport-itinerary-status-landed:var(--success-color);
        --airport-itinerary-status-arrived:var(--success-color);
        --airport-itinerary-status-connection:var(--success-color);
        --airport-itinerary-status-completed:var(--disabled-text-color);
        --airport-itinerary-progress-color:var(--primary-color);
      }
      * { box-sizing:border-box; }
      .card { padding:16px; border-radius:var(--ha-card-border-radius,12px); background:var(--ha-card-background,var(--card-background-color,#fff)); box-shadow:var(--ha-card-box-shadow,0 2px 8px #0002); }
      h2 { color:var(--ha-card-header-color,var(--primary-text-color)); font-family:var(--ha-card-header-font-family,inherit); font-size:var(--ha-card-header-font-size,var(--ha-font-size-2xl,24px)); font-weight:var(--ha-font-weight-normal,400); letter-spacing:-.012em; line-height:var(--ha-line-height-condensed,1.2); margin:0 0 12px; }
      h3 { margin:0; font-size:1.12rem; }
      .flight-heading h3 { font-size:1.22rem; }
      .muted { color:var(--secondary-text-color); font-size:.88rem; }
      .notice { min-height:1.2em; margin:8px 0; color:var(--error-color,#c62828); font-size:.9rem; }
      .notice.success { color:var(--success-color,#2e7d32); }
      .tracking-notice { padding:0 0 8px; color:var(--warning-color,var(--secondary-text-color)); font-size:.88rem; }
      label { display:block; font-size:.82rem; color:var(--secondary-text-color); margin:0 0 4px; }
      input,select { width:100%; min-height:40px; padding:8px 10px; border:1px solid var(--divider-color,#bbb); border-radius:8px; color:var(--primary-text-color); background:var(--primary-background-color,#fff); font:inherit; }
      .grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
      .field { min-width:0; display:flex; flex-direction:column; }
      .field > input,.field > select { margin-top:auto; min-width:0; max-width:100%; }
      input[type="date"],input[type="time"] { min-width:0; max-width:100%; }
      .form-actions { display:flex; flex-wrap:wrap; gap:8px; }
      @container (max-width:419px) { .grid { grid-template-columns:minmax(0,1fr) !important; } }
      .wide { grid-column:1/-1; }
      button { cursor:pointer; font:inherit; }
      .primary { border:0; border-radius:8px; min-height:40px; padding:8px 14px; color:var(--text-primary-color,#fff); background:var(--primary-color,#03a9f4); font-weight:600; }
      .secondary { border:1px solid var(--divider-color,#bbb); border-radius:8px; min-height:38px; padding:6px 10px; background:transparent; color:var(--primary-text-color); }
      button:disabled { cursor:default; opacity:.55; }
      .row { display:flex; align-items:center; justify-content:space-between; gap:12px; }
      .input-itinerary-row { display:flex; align-items:flex-end; gap:8px; margin:8px 0; }
      .input-itinerary-row .field { flex:1; }
      .input-itinerary-actions { display:flex; gap:6px; }
      .input-name-form { display:flex; align-items:center; gap:8px; margin:10px 0; }
      .input-name-form input { flex:1; min-width:0; }
      .empty-itinerary-hint { margin:10px 0; color:var(--secondary-text-color); font-size:.88rem; }
      .itinerary-row { flex-wrap:wrap; margin:8px 0; }
      .itinerary-actions,.rename-form { display:flex; align-items:center; justify-content:flex-end; gap:8px; flex-wrap:wrap; }
      .icon-action { display:inline-grid; place-items:center; width:40px; height:40px; padding:8px; }
      .icon-action ha-icon { --mdc-icon-size:20px; }
      .itinerary-name { color:var(--primary-text-color); font-size:1.25rem; font-weight:600; overflow-wrap:anywhere; }
      .rename-form input { flex:1; min-width:160px; }
      .section { padding-top:14px; margin-top:14px; border-top:1px solid var(--divider-color,#ddd); }
      .card-head { margin-bottom:12px; }
      .card-head h2 { margin:0; }
      .card-head-content { min-width:0; }
      .card-subtitle { margin-top:4px; color:var(--secondary-text-color); font-size:.86rem; }
      .collapse-toggle { flex:0 0 auto; display:inline-grid; place-items:center; width:40px; height:40px; padding:8px; }
      .collapse-toggle ha-icon { --mdc-icon-size:22px; }
      .leg-collapse { display:inline-grid; place-items:center; width:40px; height:40px; padding:8px; border-radius:50%; color:#fff; }
      .leg-collapse ha-icon { --mdc-icon-size:20px; }
      .card-content[hidden], .leg-body[hidden] { display:none; }
      .trip-select { margin:0 0 14px; }
      .itinerary-details { margin:8px 0 12px; padding:10px 0; border-top:1px solid var(--divider-color,#ddd); border-bottom:1px solid var(--divider-color,#ddd); }
      .itinerary-details summary { cursor:pointer; font-weight:600; }
      .trip-summary { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; padding-top:10px; }
      .trip-metric { min-width:0; }
      .trip-metric strong { display:block; margin-top:3px; font-size:.98rem; overflow-wrap:anywhere; }
      .leg { overflow:hidden; border:1px solid var(--divider-color,#ddd); border-radius:12px; margin-top:12px; }
      .leg-title, .leg-title * { color:#fff; }
      .leg-title { padding:12px 14px; background:color-mix(in srgb,var(--airport-itinerary-header-background,transparent) var(--airport-itinerary-header-background-opacity,100%),transparent); }
      .leg-body { padding:12px 14px; }
      .leg-heading { min-width:0; }
      .flight-heading { display:flex; align-items:center; gap:9px; flex-wrap:wrap; }
      .leg-subtitle { display:block; margin-top:2px; overflow-wrap:anywhere; }
      .schedule-route { display:grid; grid-template-columns:minmax(0,1fr) auto minmax(0,1fr); align-items:center; gap:12px; }
      .endpoint { min-width:0; }
      .endpoint:last-child { text-align:right; }
      .endpoint-label,.airport-date { color:var(--secondary-text-color); font-size:.84rem; }
      .endpoint-time { margin:2px 0; color:var(--primary-color,#03a9f4); font-size:1.75rem; font-weight:700; line-height:1.2; }
      .endpoint:last-child .endpoint-time { color:var(--primary-text-color); }
      .endpoint-code { margin-top:3px; font-size:.92rem; }

      .route-arrow { color:var(--secondary-text-color); font-size:1.2rem; }
      .schedule-progress { margin-top:14px; }
      .progress-track { position:relative; height:5px; margin:0 2px; border-radius:99px; background:var(--divider-color,#bbb); }
      .progress-fill { height:100%; border-radius:inherit; background:var(--primary-color,#03a9f4); transition:width .3s ease; }
      .progress-marker { position:absolute; top:50%; width:10px; height:10px; border:2px solid var(--ha-card-background,var(--card-background-color,#fff)); border-radius:50%; background:var(--primary-color,#03a9f4); transform:translate(-50%,-50%); }
      .progress-labels { position:relative; height:1.25em; margin-top:8px; font-size:.84rem; }
      .progress-label { position:absolute; top:0; white-space:nowrap; }
      .progress-label.centered { left:50%; transform:translateX(-50%); }
      .schedule-note { margin-top:7px; }

      .flight-details { margin-top:12px; border-top:1px solid var(--divider-color,#ddd); padding-top:9px; }
      .flight-details summary { cursor:pointer; font-weight:600; }
      .flight-detail-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 16px; padding-top:10px; }
      .flight-detail-grid strong { display:block; margin-top:2px; }
      .badges { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
      .badge { display:inline-flex; border:1px solid currentColor; border-radius:999px; padding:4px 9px; background:transparent; font-size:.8rem; font-weight:600; }
      .remove-flight { display:inline-grid; place-items:center; width:40px; height:40px; padding:8px; border-radius:50%; color:var(--error-color,#c62828); }
      .remove-flight ha-icon { --mdc-icon-size:20px; }
      .remove { color:var(--error-color,#c62828); }
      @media (max-width:520px) { .grid,.trip-summary { grid-template-columns:1fr 1fr; } .trip-metric:last-child { grid-column:1/-1; } .schedule-route { gap:7px; } .endpoint-time { font-size:1.45rem; } .progress-labels { font-size:.78rem; } }
    `;
  }

  renderShell(content) {
    const values = {};
    const active = this.shadowRoot.activeElement;
    const focusId = active?.id || "";
    let selection = null;
    if (active && typeof active.selectionStart === "number") {
      selection = {
        start: active.selectionStart,
        end: active.selectionEnd,
        direction: active.selectionDirection,
      };
    }
    if (!this._skipPreserve) {
      this.shadowRoot.querySelectorAll("input[id], select[id]").forEach((field) => {
        values[field.id] = field.value;
      });
    }
    this._skipPreserve = false;
    this.shadowRoot.innerHTML = `<style>${this.styles()}</style>${content}`;
    this.shadowRoot.querySelectorAll('input[type="date"], input[type="time"]').forEach((field) => {
      field.lang = this.displayLocale;
    });
    Object.entries(values).forEach(([id, value]) => {
      const field = this.shadowRoot.getElementById(id);
      if (field) field.value = value;
    });
    const focusedField = focusId ? this.shadowRoot.getElementById(focusId) : null;
    if (focusedField) {
      focusedField.focus({ preventScroll: true });
      if (selection && typeof focusedField.setSelectionRange === "function") {
        try {
          focusedField.setSelectionRange(selection.start, selection.end, selection.direction);
        } catch {
          // Date and time inputs do not support text selection in every browser.
        }
      }
    }
  }
}

class AirportItineraryInput extends AirportItineraryBase {
  static getConfigElement() {
    return document.createElement("airport-itinerary-input-editor");
  }

  constructor() {
    super();
    this._selected = "";
    this._nameEditorMode = "";
    this._nameDraft = "";
    this._busy = false;
    this._pendingTrip = null;
    this._inputModelSignature = null;
    this._inputCollapsed = false;
    this._inputFoldInitialized = false;
    this._initialFoldConfig = undefined;
    this._arrivalDateEdited = false;
    this._returnDraft = false;
    this._pendingFormValues = null;
  }

  setConfig(config) {
    const initialFold = config.initial_fold === true;
    if (!this._inputFoldInitialized || initialFold !== this._initialFoldConfig) {
      this._inputCollapsed = initialFold;
      this._initialFoldConfig = initialFold;
      this._inputFoldInitialized = true;
    }
    super.setConfig(config);
  }

  get refreshInterval() {
    return 0;
  }

  shouldRenderForHassChange() {
    const signature = JSON.stringify({
      services: this.servicesAvailable,
      sensor: this.model.state?.entity_id ?? null,
      itineraries: this.model.itineraries.map(({ id, name, legs }) => ({
        id,
        name,
        departures: (legs || []).map((leg) => leg.departure?.utc_timestamp),
      })),
    });
    if (signature === this._inputModelSignature) return false;
    this._inputModelSignature = signature;
    return true;
  }

  render() {
    if (!this.shadowRoot || !this._config) return;
    const itineraries = [...this.model.itineraries];
    if (this._pendingTrip) {
      if (itineraries.some((trip) => trip.id === this._pendingTrip.id)) {
        this._pendingTrip = null;
      } else {
        itineraries.push(this._pendingTrip);
      }
    }
    if (!this._selected && itineraries.length && !this._returnDraft) this._selected = itineraries[0].id;
    if (this._selected && !itineraries.some((trip) => trip.id === this._selected)) {
      this._selected = itineraries[0]?.id ?? "";
    }
    const integrationUnavailable = this._hass && !this.servicesAvailable;
    const itineraryDataUnavailable = this._hass && !this.model.state;
    const options = itineraries.map((trip) =>
      `<option value="${esc(trip.id)}" ${trip.id === this._selected ? "selected" : ""}>${esc(trip.name)}</option>`
    ).join("");
    const selectedTrip = itineraries.find((trip) => trip.id === this._selected);
    const noSelectedItinerary = !selectedTrip;
    const foldEmpty = this._config.fold_empty_itineraries !== false && noSelectedItinerary && !this._returnDraft;
    const renameAvailable = Boolean(this._hass?.services?.[DOMAIN]?.rename_itinerary);
    const nameEditor = this._nameEditorMode
      ? `<form class="input-name-form" id="itinerary-name-form"><input id="new-name" maxlength="100" required aria-label="${this._nameEditorMode === "edit" ? "Itinerary name" : "New itinerary name"}" placeholder="E.g. Copenhagen - San Francisco, Oslo - Rome, ..." value="${esc(this._nameDraft)}"><button class="secondary icon-action" type="submit" title="${this._nameEditorMode === "edit" ? "Save itinerary name" : "Create itinerary"}" aria-label="${this._nameEditorMode === "edit" ? "Save itinerary name" : "Create itinerary"}" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:check" aria-hidden="true"></ha-icon></button><button class="secondary icon-action" id="cancel-name-edit" type="button" title="Cancel" aria-label="Cancel" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:close" aria-hidden="true"></ha-icon></button></form>`
      : "";
    this.renderShell(`
      <section class="card">
        <div class="row card-head"><h2>${esc(this._config.title || "Add a flight")}</h2><button class="secondary collapse-toggle" id="toggle-input-collapse" type="button" title="${this._inputCollapsed ? "Expand" : "Collapse"} flight form" aria-label="${this._inputCollapsed ? "Expand" : "Collapse"} flight form" aria-expanded="${!this._inputCollapsed}"><ha-icon icon="${this._inputCollapsed ? "mdi:chevron-down" : "mdi:chevron-up"}" aria-hidden="true"></ha-icon></button></div>
        <div class="card-content" ${this._inputCollapsed ? "hidden" : ""}>
          <div class="input-itinerary-row"><div class="field"><label for="trip">Itinerary</label><select id="trip"><option value="">Choose an itinerary</option>${options}</select></div><div class="input-itinerary-actions"><button class="secondary icon-action" id="create-itinerary" type="button" title="Create itinerary" aria-label="Create itinerary" ${integrationUnavailable || this._busy ? "disabled" : ""}><ha-icon icon="mdi:plus" aria-hidden="true"></ha-icon></button><button class="secondary icon-action" id="edit-itinerary" type="button" title="Edit itinerary name" aria-label="Edit itinerary name" ${!selectedTrip || !renameAvailable || this._busy ? "disabled" : ""}><ha-icon icon="mdi:pencil" aria-hidden="true"></ha-icon></button></div></div>
          ${nameEditor}
          <div class="notice ${this._messageType === "success" ? "success" : ""}" role="status">${esc(this._message || (integrationUnavailable ? "The Airport-aware Flight Itinerary integration is not active. Add it in Settings > Devices & services and resolve any setup errors before creating itineraries." : itineraryDataUnavailable ? `The itinerary sensor was not found. Checked ${this._config.entity}; looking for a sensor with itinerary data.` : ""))}</div>
          ${foldEmpty ? `<div class="empty-itinerary-hint">Create or select an itinerary to add a flight.</div>` : ""}
          <div class="section" ${foldEmpty ? "hidden" : ""}>
            <form id="flight-form">
              <div class="grid" style="margin-top:10px">
              <div class="field"><label for="number">Flight number</label><input id="number" name="flight_number" required maxlength="16" placeholder="SK935, DY1870"></div>
              <div class="field"><label for="label">Flight label (optional)</label><input id="label" name="label" maxlength="80" placeholder="CPH-SFO"></div>
              <div class="field"><label for="origin">Origin airport</label><input id="origin" name="origin_airport" required minlength="3" maxlength="3" placeholder="CPH" autocapitalize="characters"></div>
              <div class="field"><label for="destination">Destination airport (optional)</label><input id="destination" name="destination_airport" minlength="3" maxlength="3" placeholder="SFO" autocapitalize="characters"></div>
              <div class="field"><label for="date">Flight date at origin</label><input id="date" name="service_date" type="date" required></div>
              <div class="field"><label for="departure">Departure time at origin</label><input id="departure" name="departure_time" type="time" required></div>
              <div class="field"><label for="arrival-date">Expected arrival date at destination (optional)</label><input id="arrival-date" name="arrival_date" type="date"></div>
              <div class="field"><label for="arrival">Expected arrival time (optional)</label><input id="arrival" name="arrival_time" type="time"></div>
              <div class="field"><label for="fold">Repeated departure time</label><select id="fold" name="fold"><option value="">Automatic (not repeated)</option><option value="earlier">Earlier occurrence</option><option value="later">Later occurrence</option></select></div>
              <div class="field"><label for="arrival-fold">Repeated arrival time</label><select id="arrival-fold" name="arrival_fold"><option value="">Automatic (not repeated)</option><option value="earlier">Earlier occurrence</option><option value="later">Later occurrence</option></select></div>
              <div class="muted wide">If clocks move back and your time occurs twice, choose the earlier or later occurrence at that airport.</div>
              <div class="wide form-actions"><button class="primary" type="submit" ${this._selected && !integrationUnavailable && !this._busy ? "" : "disabled"}>Add flight to itinerary</button>${selectedTrip && !selectedTrip.legs?.length && !this._returnDraft ? `<button class="secondary" type="submit" name="prepare_return" value="yes" ${this._busy ? "disabled" : ""}>Add + prepare return</button>` : ""}</div>
              </div>
            </form>
          </div>
        </div>
      </section>`);
    const tripSelect = this.shadowRoot.querySelector("#trip");
    if (tripSelect) tripSelect.value = this._selected;
    if (this._pendingFormValues) {
      Object.entries(this._pendingFormValues).forEach(([id, value]) => {
        const field = this.shadowRoot.getElementById(id);
        if (field) field.value = value;
      });
      this._pendingFormValues = null;
    }
    this.shadowRoot.querySelector("#date")?.addEventListener("input", (event) => {
      if (!this._arrivalDateEdited) this.shadowRoot.querySelector("#arrival-date").value = event.target.value;
    });
    this.shadowRoot.querySelector("#arrival-date")?.addEventListener("input", () => {
      this._arrivalDateEdited = true;
    });
    this.shadowRoot.querySelector("#toggle-input-collapse")?.addEventListener("click", () => {
      this._inputCollapsed = !this._inputCollapsed;
      this.render();
    });
    this.shadowRoot.querySelector("#trip")?.addEventListener("change", (event) => {
      if (this._busy) return;
      if (this._returnDraft) this._cancelReturnDraft();
      this._selected = event.target.value;
      this._nameEditorMode = "";
      this._message = "";
      this._messageType = "error";
      this.render();
    });
    this.shadowRoot.querySelector("#create-itinerary")?.addEventListener("click", () => {
      this._nameEditorMode = "create";
      this._nameDraft = "";
      this.render();
      this.shadowRoot.querySelector("#new-name")?.focus();
    });
    this.shadowRoot.querySelector("#edit-itinerary")?.addEventListener("click", () => {
      this._nameEditorMode = "edit";
      this._nameDraft = selectedTrip?.name ?? "";
      this.render();
      const input = this.shadowRoot.querySelector("#new-name");
      input?.focus();
      input?.select();
    });
    this.shadowRoot.querySelector("#cancel-name-edit")?.addEventListener("click", () => {
      if (this._returnDraft) this._cancelReturnDraft();
      this._nameEditorMode = "";
      this._nameDraft = "";
      this.render();
    });
    this.shadowRoot.querySelector("#new-name")?.addEventListener("input", (event) => {
      this._nameDraft = event.currentTarget.value;
    });
    this.shadowRoot.querySelector("#label")?.addEventListener("input", (event) => {
      const match = event.currentTarget.value.trim().match(/^([A-Z0-9]{3})-([A-Z0-9]{3})$/i);
      if (!match) return;
      this.shadowRoot.querySelector("#origin").value = match[1].toUpperCase();
      this.shadowRoot.querySelector("#destination").value = match[2].toUpperCase();
    });
    this.shadowRoot.querySelector("#itinerary-name-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = this.shadowRoot.querySelector("#new-name")?.value.trim();
      if (!name || this._busy) return;
      const mode = this._nameEditorMode;
      this._busy = true;
      this._message = "";
      this.render();
      try {
        const response = mode === "edit"
          ? await this.call("rename_itinerary", { itinerary_id: this._selected, name })
          : await this.call("create_itinerary", { name });
        this._selected = response.itinerary?.id ?? this._selected;
        this._pendingTrip = response.itinerary ?? this._pendingTrip;
        this._returnDraft = false;
        this._nameEditorMode = "";
        this._nameDraft = "";
        this._message = mode === "edit" ? "Itinerary name updated." : "Itinerary created.";
        this._messageType = "success";
      } catch (error) {
        this._message = error.message;
        this._messageType = "error";
      } finally {
        this._busy = false;
        this.render();
      }
    });
    this.shadowRoot.querySelector("#flight-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (this._busy || !this._selected) return;
      const form = event.currentTarget;
      const values = Object.fromEntries(new FormData(form).entries());
      const prepareReturn = event.submitter?.name === "prepare_return";
      if (prepareReturn && (!values.destination_airport || selectedTrip?.legs?.length)) {
        this._message = "Enter both airports to prepare a return for a single-flight itinerary.";
        this._messageType = "error";
        this.render();
        return;
      }
      if (!this._arrivalDateEdited && !values.arrival_time) delete values.arrival_date;
      const payload = Object.fromEntries(Object.entries(values).filter(([, value]) => value !== ""));
      this._busy = true;
      const sourceTrip = this._selected;
      this.render();
      try {
        this._message = "";
        this._messageType = "error";
        const response = await this.call("add_flight", { itinerary_id: this._selected, ...payload });
        this._pendingTrip = response.itinerary ?? this._pendingTrip;
        this._skipPreserve = true;
        this._arrivalDateEdited = false;
        this._message = "Flight added.";
        this._messageType = "success";
        if (prepareReturn && response.itinerary?.legs?.length === 1) {
          const origin = values.destination_airport.trim().toUpperCase();
          const destination = values.origin_airport.trim().toUpperCase();
          const date = values.arrival_date || values.service_date;
          this._returnDraft = true;
          this._returnSourceTrip = sourceTrip;
          this._selected = "";
          this._nameEditorMode = "create";
          this._nameDraft = `${origin}-${destination}`;
          this._pendingFormValues = { origin, destination, label: `${origin}-${destination}`, date, "arrival-date": date };
          this._message = "Outbound saved. Create the return itinerary, then enter its flight number and times. Cancel to discard this draft.";
        }
      } catch (error) {
        this._message = error.message;
        this._messageType = "error";
      } finally {
        this._busy = false;
        this.render();
      }
    });
  }

  _cancelReturnDraft() {
    this._returnDraft = false;
    this._selected = this._returnSourceTrip || "";
    this._pendingFormValues = null;
    this._arrivalDateEdited = false;
    this._skipPreserve = true;
  }
}

class AirportItinerarySchedule extends AirportItineraryBase {
  static getConfigElement() {
    return document.createElement("airport-itinerary-schedule-editor");
  }

  constructor() {
    super();
    this._selected = "";
    this._manualSelection = false;
    this._busy = false;
    this._editingName = false;
    this._nameDraft = "";
    this._scheduleModelSignature = null;
    this._pendingDeletedIds = new Set();
    this._collapseItineraryId = "";
    this._collapseOverride = null;
    this._legCollapseOverrides = new Map();
  }

  getFinishedAt(trip, trackedLegs, now) {
    const legs = trip?.legs ?? [];
    if (!legs.length) return null;
    const configuredDelay = Number(this._config.finish_delay_seconds);
    const delayMs = (Number.isFinite(configuredDelay) ? Math.max(0, configuredDelay) : 300) * 1000;
    const finishTimes = legs.map((leg) => {
      const tracked = trackedLegs.find((item) => item.itinerary_id === trip.id && item.leg_id === leg.id);
      const arrival = arrivalState(leg, tracked, now);
      const actualFinishedAt = arrival.finalAt;
      if (actualFinishedAt != null) return actualFinishedAt + delayMs;
      if (arrival.landed || arrival.arrived) return null;
      const arrivalMs = stamp(leg.arrival?.utc_timestamp);
      if (arrivalMs == null) return null;
      const updatedAt = stamp(tracked?.position_updated_at);
      const positionFresh = tracked?.is_live === true && isFreshUpdate(updatedAt, now);
      const liveOngoing = positionFresh && [true, false].includes(tracked?.on_ground) && !leg.completed;
      if (liveOngoing) return null;
      return arrivalMs + delayMs;
    });
    if (finishTimes.some((time) => time == null)) return null;
    return Math.max(...finishTimes);
  }

  shouldRenderForHassChange() {
    const { state, itineraries, tracked } = this.model;
    const signature = JSON.stringify({
      sensor: state?.entity_id ?? null,
      itineraries,
      tracked,
      tracking: state?.attributes?.tracking,
      journeys: state?.attributes?.journeys,
      trackingHealth: state?.attributes?.tracking_source_health,
      connectionEntity: state?.attributes?.fr24_connection_entity,
      sourceFlights: this._hass?.states?.[state?.attributes?.tracking_source_entity]?.attributes?.flights,
    });
    if (signature === this._scheduleModelSignature) return false;
    this._scheduleModelSignature = signature;
    return true;
  }

  shouldDeferRender() {
    return Boolean(this.shadowRoot.activeElement);
  }

  render() {
    if (!this.shadowRoot || !this._config) return;
    this._pendingRender = false;
    const { itineraries, tracked, state } = this.model;
    for (const id of this._pendingDeletedIds) {
      if (!itineraries.some((item) => item.id === id)) this._pendingDeletedIds.delete(id);
    }
    const pinned = this._config.itinerary_id;
    const available = itineraries.filter((item) => !this._pendingDeletedIds.has(item.id));
    const trips = pinned ? available.filter((trip) => trip.id === pinned) : available;
    const now = Date.now();
    const selected = trips.find((item) => item.id === this._selected);
    if (!selected) this._manualSelection = false;
    const trip = pinned ? trips[0]
      : selected && (this._manualSelection || this._editingName || this._busy) ? selected
        : preferredItinerary(trips, state?.attributes?.journeys, now,
          Number.isFinite(Number(this._config.finish_delay_seconds)) ? Math.max(0, Number(this._config.finish_delay_seconds)) : 300);
    if (trip) this._selected = trip.id;
    const selector = !pinned && trips.length > 1
      ? `<div class="field trip-select"><label for="trip">Itinerary</label><select id="trip">${trips.map((item) => `<option value="${esc(item.id)}" ${item.id === trip?.id ? "selected" : ""}>${esc(item.name)}</option>`).join("")}</select></div>`
      : "";
    const legs = trip?.legs ?? [];
    const first = legs[0];
    const last = legs.at(-1);
    const startMs = stamp(first?.departure?.utc_timestamp);
    const arrivalMs = stamp(last?.arrival?.utc_timestamp);
    const totalSeconds = startMs && arrivalMs && arrivalMs > startMs ? (arrivalMs - startMs) / 1000 : null;
    const rawElapsedSeconds = startMs && now >= startMs ? (now - startMs) / 1000 : null;
    const elapsedSeconds = rawElapsedSeconds == null
      ? null
      : totalSeconds == null ? rawElapsedSeconds : Math.min(rawElapsedSeconds, totalSeconds);
    const remainingSeconds = arrivalMs ? Math.max(0, (arrivalMs - now) / 1000) : null;
    const retainedTiming = retainedJourneyTiming(trip, tracked, now);
    const journey = trip ? `<details class="itinerary-details">
      <summary>Itinerary details</summary>
      <div class="trip-summary">
        <div class="trip-metric"><span class="muted">${retainedTiming?.label || "Scheduled travel time"}</span><strong>${retainedTiming?.elapsed ?? (totalSeconds == null ? "Awaiting final arrival" : duration(totalSeconds))}</strong></div>
        <div class="trip-metric"><span class="muted">${retainedTiming ? "Scheduled travel time" : "Scheduled time elapsed"}</span><strong>${retainedTiming ? (totalSeconds == null ? "Arrival not entered" : duration(totalSeconds)) : elapsedSeconds == null ? "Not started" : duration(elapsedSeconds)}</strong></div>
        <div class="trip-metric"><span class="muted">${retainedTiming ? "Arrival status" : "Scheduled time remaining"}</span><strong>${retainedTiming?.status ?? (remainingSeconds == null ? "Awaiting final arrival" : remainingSeconds === 0 ? "Scheduled arrival passed" : duration(remainingSeconds))}</strong></div>
      </div>
      <div class="muted trip-summary-note">${retainedTiming?.note || "These summary durations use the entered schedule. Recorded actual times are retained in the flight details."}</div>
    </details>` : "";
    const trackingHealth = state?.attributes?.tracking_source_health;
    const trackingMessages = {
      disabled: "Schedule-only mode. The FR24 connection is off; your connection settings are saved.",
      not_configured: "Connect the Flightradar24 Additional tracked sensor in the integration options to show live flight data.",
      entity_missing: "The configured FR24 sensor is missing; showing the itinerary schedule.",
      unavailable: "The FR24 sensor is unavailable; showing the itinerary schedule.",
      unsupported_data: "The FR24 sensor does not provide a flights list; showing the itinerary schedule.",
      no_flights: "Waiting for FR24 flight records; showing the itinerary schedule.",
      no_matching_flight: "FR24 has flight records, but none match this itinerary's flight number, airports, and departure time.",
    };
    let trackingMessage = trackingMessages[trackingHealth];
    const control = state?.attributes?.tracking;
    const waitingDetails = waitingForFlightDetails(legs, this._hass?.states?.[state?.attributes?.tracking_source_entity]?.attributes?.flights);
    const selectedJourneys = (state?.attributes?.journeys || []).filter((item) => item.itinerary_id === trip?.id);
    const futureStart = selectedJourneys.map((item) => stamp(item.api_start_at)).filter((value) => value > now).sort((a, b) => a - b)[0];
    const arrivalsRetained = legs.length > 0 && legs.every((leg) => {
      const arrival = arrivalState(leg, tracked.find((item) => item.itinerary_id === trip?.id && item.leg_id === leg.id), now);
      return leg.completed || arrival.completedAt != null || arrival.landed || arrival.arrived;
    });
    if (arrivalsRetained) {
      // Provider cleanup is expected after arrival; it is not a new request
      // waiting for FR24 to resolve the already observed flight.
      trackingMessage = null;
    } else if (["no_flights", "no_matching_flight", "scheduled_match", "live_match"].includes(trackingHealth)
        && !tracked.some((item) => item.itinerary_id === trip?.id)) {
      trackingMessage = futureStart && !selectedJourneys.some((item) => item.tracking_required)
        ? `Tracking starts ${new Date(futureStart).toLocaleString(this.displayLocale)}; showing the saved schedule.`
        : control?.fetching === false ? "FR24 API fetching is off; showing the itinerary schedule."
          : waitingDetails ? "Added to FR24—waiting for flight details"
            : control?.auto_track ? "Waiting for FR24 to resolve this flight occurrence; showing the saved schedule."
            : trackingMessages[trackingHealth] || trackingMessages.no_matching_flight;
    }
    const trackingNotice = trackingMessage
      ? `<div class="tracking-notice" role="status">${esc(trackingMessage)}</div>`
      : "";
    const connectionEntity = state?.attributes?.fr24_connection_entity;
    const connectionEnabled = control?.connection_enabled !== false;
    const connectionToggle = this._config.show_fr24_connection_control === true && connectionEntity
      ? `<button id="fr24-connection" class="secondary" type="button" role="switch" aria-label="FR24 connection" aria-checked="${connectionEnabled}" ${this._connectionBusy ? "disabled" : ""} title="Switch between live tracking and schedule-only mode; keep FR24 settings">${connectionEnabled ? "Live tracking" : "Schedule only"}</button>`
      : "";
    const cards = legs.map((leg, index) => this.renderLeg(trip, leg, index, tracked, now)).join("");
    if (this._collapseItineraryId !== (trip?.id ?? "")) {
      this._collapseItineraryId = trip?.id ?? "";
      this._collapseOverride = null;
    }
    const finishedAt = this.getFinishedAt(trip, tracked, now);
    const allLegsFinished = finishedAt != null && now >= finishedAt;
    const isCollapsed = this._collapseOverride === true;
    const itineraryTitle = this._config.title || trip?.name || "Flight itinerary";
    const collapseSubtitle = isCollapsed && trip
      ? `${trip.name !== itineraryTitle ? `${esc(trip.name)} · ` : ""}${legs.length} ${legs.length === 1 ? "flight" : "flights"}${allLegsFinished ? " · Finished" : ""}`
      : "";
    const collapseToggle = trip
      ? `<button class="secondary collapse-toggle" id="toggle-collapse" type="button" title="${isCollapsed ? "Expand" : "Collapse"} itinerary" aria-label="${isCollapsed ? "Expand" : "Collapse"} itinerary" aria-expanded="${!isCollapsed}"><ha-icon icon="${isCollapsed ? "mdi:chevron-down" : "mdi:chevron-up"}" aria-hidden="true"></ha-icon></button>`
      : "";
    const itineraryActions = trip ? this._editingName
      ? `<form id="rename-form" class="rename-form"><input id="itinerary-name" maxlength="100" required aria-label="Itinerary name" value="${esc(this._nameDraft)}"><button class="primary" type="submit" ${this._busy ? "disabled" : ""}>Save</button><button class="secondary" id="cancel-rename" type="button" ${this._busy ? "disabled" : ""}>Cancel</button></form>`
      : `<div class="itinerary-actions"><button class="secondary icon-action" id="edit-name" type="button" title="Edit itinerary name" aria-label="Edit itinerary name" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:pencil" aria-hidden="true"></ha-icon></button><button class="secondary remove icon-action" id="delete-itinerary" type="button" title="Remove itinerary" aria-label="Remove itinerary" ${this._busy ? "disabled" : ""}><ha-icon icon="mdi:trash-can-outline" aria-hidden="true"></ha-icon></button></div>`
      : "";
    this.renderShell(`
      <section class="card">
        <div class="row card-head"><div class="card-head-content"><h2>${esc(itineraryTitle)}</h2>${collapseSubtitle ? `<div class="card-subtitle">${collapseSubtitle}</div>` : ""}</div>${collapseToggle}</div>
        <div class="card-content" ${isCollapsed ? "hidden" : ""}>
          ${selector}${connectionToggle}${trackingNotice}${trip ? `<div class="row itinerary-row"><div class="itinerary-name">${esc(trip.name)}</div>${itineraryActions}</div>` : ""}${journey}
          ${trip ? cards || '<div class="section muted">No flights in this itinerary yet.</div>' : this.model.state ? '<div class="muted">No itinerary found. Use the itinerary input card to create one.</div>' : `<div class="muted">Itinerary data is unavailable. Checked ${esc(this._config.entity)} and looked for a sensor with itinerary data.</div>`}
          <div class="notice ${this._messageType === "success" ? "success" : ""}" role="status">${esc(this._message)}</div>
        </div>
      </section>`);
    const tripSelect = this.shadowRoot.querySelector("#trip");
    if (tripSelect) tripSelect.value = trip?.id ?? "";
    this.shadowRoot.querySelector("#fr24-connection")?.addEventListener("click", async () => {
      if (this._connectionBusy) return;
      this._connectionBusy = true;
      this._message = "";
      this.render();
      try {
        await this._hass.callService("switch", connectionEnabled ? "turn_off" : "turn_on", { entity_id: connectionEntity });
      } catch (error) {
        this._message = error.message;
        this._messageType = "error";
      } finally {
        this._connectionBusy = false;
        this.render();
      }
    });
    this.shadowRoot.querySelector("#toggle-collapse")?.addEventListener("click", () => {
      this._collapseOverride = !isCollapsed;
      this.render();
    });
    this.shadowRoot.querySelectorAll("[data-collapse-flight]").forEach((button) =>
      button.addEventListener("click", () => {
        const legId = button.dataset.collapseFlight;
        const collapsed = button.dataset.collapsed === "true";
        this._legCollapseOverrides.set(legId, !collapsed);
        this.render();
      })
    );
    this.shadowRoot.querySelector("#trip")?.addEventListener("change", (event) => {
      this._selected = event.target.value;
      this._manualSelection = true;
      this._editingName = false;
      this._message = "";
      this.render();
    });
    this.shadowRoot.querySelector("#edit-name")?.addEventListener("click", () => {
      this._editingName = true;
      this._nameDraft = trip.name;
      this.render();
      this.shadowRoot.querySelector("#itinerary-name")?.focus();
    });
    this.shadowRoot.querySelector("#itinerary-name")?.addEventListener("input", (event) => {
      this._nameDraft = event.currentTarget.value;
    });
    this.shadowRoot.querySelector("#cancel-rename")?.addEventListener("click", () => {
      this._editingName = false;
      this._message = "";
      this.render();
    });
    this.shadowRoot.querySelector("#rename-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = this.shadowRoot.querySelector("#itinerary-name").value.trim();
      if (!name) {
        this._message = "Enter an itinerary name.";
        this._messageType = "error";
        this.render();
        return;
      }
      this._busy = true;
      try {
        await this.call("rename_itinerary", { itinerary_id: trip.id, name });
        this._editingName = false;
        this._message = "Itinerary renamed.";
        this._messageType = "success";
      } catch (error) {
        this._message = error.message;
        this._messageType = "error";
      } finally {
        this._busy = false;
        this.render();
      }
    });
    this.shadowRoot.querySelector("#delete-itinerary")?.addEventListener("click", async () => {
      if (this._busy || !window.confirm(`Remove "${trip.name}" and all of its flights?`)) return;
      this._busy = true;
      try {
        await this.call("delete_itinerary", { itinerary_id: trip.id });
        this._pendingDeletedIds.add(trip.id);
        this._selected = "";
        this._manualSelection = false;
        this._editingName = false;
        this._message = "Itinerary removed.";
        this._messageType = "success";
      } catch (error) {
        this._message = error.message;
        this._messageType = "error";
      } finally {
        this._busy = false;
        this.render();
      }
    });
    this.shadowRoot.querySelectorAll("[data-remove]").forEach((button) =>
      button.addEventListener("click", async () => {
        if (this._busy) return;
        this._busy = true;
        try {
          await this.call("remove_flight", { itinerary_id: trip.id, leg_id: button.dataset.remove });
          this._message = "Flight removed.";
          this._messageType = "success";
        } catch (error) {
          this._message = error.message;
          this._messageType = "error";
        } finally {
          this._busy = false;
          this.render();
        }
      })
    );
    this.shadowRoot.querySelectorAll("[data-complete]").forEach((button) =>
      button.addEventListener("click", async () => {
        if (this._busy || !window.confirm("Mark this flight completed? This stops automatic additions and queues cleanup of integration-owned tracking. It does not record an actual landing.")) return;
        this._busy = true;
        try {
          await this.call("mark_flight_completed", { itinerary_id: trip.id, leg_id: button.dataset.complete });
          this._message = "Flight manually completed.";
          this._messageType = "success";
        } catch (error) {
          this._message = error.message;
          this._messageType = "error";
        } finally {
          this._busy = false;
          this.render();
        }
      })
    );
  }

  renderLeg(trip, leg, index, trackedLegs, now) {
    const dep = leg.departure || {};
    const arr = leg.arrival || {};
    const depMs = stamp(dep.utc_timestamp);
    const arrMs = stamp(arr.utc_timestamp);
    const origin = leg.origin_airport || dep.airport || "Origin";
    const destination = leg.destination_airport || arr.airport || "Destination";
    const destinationZone = leg.destination_timezone || arr.timezone || "";
    const tracked = trackedLegs.find((item) => item.itinerary_id === trip.id && item.leg_id === leg.id);
    const liveTracked = tracked?.is_live === true ? tracked : null;
    const airportNames = this._config.airport_names ?? {};
    const originCity = airportNames[origin] || leg.origin_city || dep.city || tracked?.airport_origin_city || "";
    const destinationCity = airportNames[destination] || leg.destination_city || arr.city || tracked?.airport_destination_city || "";
    const durationSeconds = Number.isFinite(leg.flight_time_seconds)
      ? leg.flight_time_seconds
      : depMs && arrMs && arrMs > depMs ? (arrMs - depMs) / 1000 : null;
    const sourceUpdated = stamp(tracked?.position_updated_at);
    const sourceFresh = isFreshUpdate(sourceUpdated, now);
    const positionFresh = Boolean(liveTracked && sourceFresh);
    const actualDeparture = stamp(tracked?.time_real_departure) || stamp(leg.evidence?.departure);
    const estimatedDeparture = sourceFresh ? stamp(tracked?.time_estimated_departure) : null;
    const arrival = arrivalState(leg, tracked, now);
    const actualArrival = arrival.gateAt || arrival.landedAt;
    const arrivalObserved = arrival.arrived || arrival.landed || arrival.landedAt != null;
    const timingFinished = arrivalObserved || leg.completed || arrival.completedAt != null;
    const elapsedStart = actualDeparture || depMs;
    const elapsedEnd = arrival.arrived ? arrival.gateAt : arrival.landedAt;
    const elapsedLabel = arrival.arrived ? "Departure to gate"
      : arrivalObserved ? "Departure to landing"
        : timingFinished ? "Actual duration"
          : actualDeparture ? "Time since departure" : "Time since scheduled departure";
    // Completed flights must never use the current clock or a scheduled time
    // as a substitute for a missing actual departure/arrival timestamp.
    const elapsedValue = timingFinished
      ? actualDeparture != null && elapsedEnd != null && elapsedEnd >= actualDeparture
        ? duration((elapsedEnd - actualDeparture) / 1000) : "Unavailable"
      : duration((now - elapsedStart) / 1000);
    const showElapsed = timingFinished || elapsedStart != null && now > elapsedStart;
    const estimatedArrival = sourceFresh ? stamp(tracked?.time_estimated_arrival) : null;
    const displayDeparture = actualDeparture || estimatedDeparture || depMs;
    const displayArrival = actualArrival || estimatedArrival || arrMs;
    const progressDeparture = displayDeparture || depMs;
    const progressArrival = displayArrival || arrMs;
    const timeProgress = progressDeparture && progressArrival && progressArrival > progressDeparture
      ? Math.min(100, Math.max(0, ((now - progressDeparture) / (progressArrival - progressDeparture)) * 100))
      : null;
    const departureLabel = actualDeparture ? "Departed"
      : estimatedDeparture ? "Estimated departure"
      : "Scheduled departure";
    const arrivalLabel = actualArrival
      ? (arrival.gateAt ? "Final arrival" : "Landed")
      : estimatedArrival ? "Estimated arrival"
      : arrMs ? "Scheduled arrival" : "Expected arrival";
    const positionProgress = positionFresh
      ? routeProgress(leg.origin_coordinates, leg.destination_coordinates, liveTracked)
      : null;
    const liveProgress = liveTracked ? (actualArrival ? 100 : positionProgress) : null;
    const progress = arrival.arrived || arrival.landed ? 100 : liveProgress ?? timeProgress;
    const timeBasis = estimatedArrival ? "estimated" : "scheduled";
    const scheduleStatus = timeProgress == null ? "Add an expected arrival to show schedule progress."
      : now < progressDeparture ? `Departs in ${duration((progressDeparture - now) / 1000)} (${estimatedDeparture ? "estimated" : "scheduled"})`
      : now < progressArrival ? `${duration((progressArrival - now) / 1000)} remaining (${timeBasis})`
      : `${estimatedArrival ? "Estimated" : "Scheduled"} arrival was ${duration((now - progressArrival) / 1000)} ago · actual arrival not confirmed`;
    const progressLabel = arrival.arrived ? "Final arrival · at gate"
      : arrival.taxiing ? "Taxiing to gate · awaiting final arrival"
      : arrival.landed ? "Landed · awaiting gate confirmation"
      : liveProgress != null
      ? `Live position · ${Math.round(liveProgress)}% complete`
      : scheduleStatus;
    const hasArrived = arrival.arrived;
    const isLanded = arrival.landed;
    const previousLeg = index > 0 ? trip.legs[index - 1] : null;
    const previousTracked = previousLeg && trackedLegs.find((item) => item.itinerary_id === trip.id && item.leg_id === previousLeg.id && item.is_live === true);
    const isConnection = Boolean(previousTracked?.time_real_arrival || previousTracked?.landing || previousTracked?.gate_arrival)
      && depMs != null && now < depMs && !hasArrived;
    const isAirborne = positionFresh && liveTracked?.on_ground === false
      && !hasArrived && !isLanded && !leg.completed;
    const isOnGround = positionFresh && liveTracked?.on_ground === true
      && !hasArrived && !isLanded && !leg.completed && !leg.finished_at;
    const isInTransit = Boolean(liveTracked?.time_real_departure)
      && !hasArrived && !isLanded && !isAirborne && !leg.completed;
    const isCompleted = Boolean(leg.completed || hasArrived);
    const actualFinishedAt = arrival.finalAt;
    const scheduledFinishedAt = actualFinishedAt == null && arrMs != null && !isAirborne && !isOnGround && !isLanded && !hasArrived
      ? arrMs
      : null;
    const finishedAt = actualFinishedAt || scheduledFinishedAt;
    const finishDelaySeconds = Number.isFinite(Number(this._config.finish_delay_seconds))
      ? Math.max(0, Number(this._config.finish_delay_seconds))
      : 300;
    const isFinishing = finishedAt != null && now >= finishedAt && now < finishedAt + finishDelaySeconds * 1000;
    const isFinished = finishedAt != null && now >= finishedAt + finishDelaySeconds * 1000;
    const autoCollapseMinutes = Number(this._config.auto_collapse_after_minutes);
    const autoCollapseAt = Number.isFinite(autoCollapseMinutes) && autoCollapseMinutes > 0 && finishedAt != null
      ? finishedAt + (finishDelaySeconds + autoCollapseMinutes * 60) * 1000
      : null;
    const autoCollapsed = autoCollapseAt != null && now >= autoCollapseAt;
    const isLegCollapsed = this._legCollapseOverrides.has(leg.id)
      ? this._legCollapseOverrides.get(leg.id)
      : autoCollapsed;
    const status = isFinished && actualFinishedAt == null && !hasArrived && !isLanded && !leg.completed
      ? "Finished (scheduled)"
      : isFinishing && scheduledFinishedAt != null && !hasArrived && !isLanded && !leg.completed
        ? "Scheduled arrival passed"
        : isAirborne ? "Airborne"
        : hasArrived ? "Final arrival · at gate"
        : arrival.taxiing ? "Taxiing to gate"
        : isLanded ? "Landed · awaiting gate"
        : leg.completed ? (leg.evidence?.manual_completion ? "Completed manually" : leg.evidence?.inferred_completion ? "Completed (inferred)" : "Completed")
        : isOnGround ? "On ground"
        : isInTransit ? "In transit"
        : isConnection ? "Connection"
        : "Scheduled";
    const statusKey = isAirborne ? "airborne" : hasArrived ? "arrived" : isLanded ? "landed"
      : leg.completed ? "completed" : isConnection ? "connection"
        : isOnGround || isInTransit ? "in_transit" : "scheduled";
    const configuredColor = (value) => typeof value === "string" && value.trim() !== "";
    const hasStatusColor = configuredColor(this._config.status_colors?.[statusKey]);
    const hasProgressColor = configuredColor(this._config.progress_color);
    const useFinishedOverride = isFinished && configuredColor(this._config.finished_color);
    const finishedColor = "var(--airport-itinerary-finished-color,var(--disabled-text-color))";
    const statusColor = useFinishedOverride ? finishedColor : "var(" + STATUS_COLOR_CONFIG[statusKey] + ")";
    // At the gate, both times and progress follow the displayed status colour.
    // Before gate arrival, explicit colours outrank defaults.
    // A configured finished colour is the phase-specific override after finishing.
    const progressColor = hasArrived ? statusColor : useFinishedOverride ? finishedColor
      : hasProgressColor ? "var(--airport-itinerary-progress-color)"
        : hasStatusColor ? statusColor
          : isFinished ? finishedColor
            : tracked || isCompleted || isLanded ? statusColor : "var(--disabled-text-color)";
    const colourTimes = useFinishedOverride || hasProgressColor || hasStatusColor || tracked || isCompleted || isLanded || isFinished;
    const departureTimeColor = colourTimes ? progressColor
      : displayDeparture != null && now >= displayDeparture ? "var(--primary-color)" : "var(--primary-text-color)";
    // An estimate, elapsed schedule or manual completion does not prove landing.
    // Retained landing/gate evidence survives provider cleanup and restarts.
    const arrivalConfirmed = hasArrived || isLanded || arrival.landedAt != null;
    const arrivalTimeColor = arrivalConfirmed ? progressColor : "var(--primary-text-color)";
    const originZone = dep.timezone || "";

    const flightLabel = leg.label || `${origin}-${destination}`;
    const legClasses = [isCompleted ? "completed" : "", isFinishing ? "finishing" : "", isFinished ? "finished" : ""].filter(Boolean).join(" ");
    return `<article class="leg ${legClasses}">
      <div class="leg-title row"><div class="leg-heading"><div class="flight-heading"><h3>${esc(leg.flight_number || "Flight")}</h3><span class="flight-label">· ${esc(flightLabel)}</span><span class="badge" style="color:${statusColor}">${esc(status)}</span></div></div><div class="badges"><button class="secondary leg-collapse" data-collapse-flight="${esc(leg.id)}" data-collapsed="${isLegCollapsed}" type="button" title="${isLegCollapsed ? "Expand" : "Collapse"} flight" aria-label="${isLegCollapsed ? "Expand" : "Collapse"} ${esc(leg.flight_number || "flight")}" aria-expanded="${!isLegCollapsed}"><ha-icon icon="${isLegCollapsed ? "mdi:chevron-down" : "mdi:chevron-up"}" aria-hidden="true"></ha-icon></button>${this._config.show_finish_flight_control === true && !leg.completed && this._hass?.services?.[DOMAIN]?.mark_flight_completed ? `<button class="secondary icon-action" data-complete="${esc(leg.id)}" title="Mark completed" aria-label="Mark ${esc(leg.flight_number)} completed"><ha-icon icon="mdi:check" aria-hidden="true"></ha-icon></button>` : ""}<button class="secondary remove-flight" data-remove="${esc(leg.id)}" title="Remove flight" aria-label="Remove ${esc(leg.flight_number || "flight")}"><ha-icon icon="mdi:trash-can-outline" aria-hidden="true"></ha-icon></button></div></div>
      <div class="leg-body" ${isLegCollapsed ? "hidden" : ""}>
        <div class="schedule-route">
          <div class="endpoint"><div class="endpoint-label">${departureLabel}</div><div class="endpoint-time" style="color:${departureTimeColor}">${displayDeparture ? esc(airportTime(new Date(displayDeparture).toISOString(), originZone, this.displayLocale)) : "—"}</div><div class="airport-date">${displayDeparture ? `${esc(airportDate(new Date(displayDeparture).toISOString(), originZone, this.displayLocale))} · ${esc(airportZoneName(new Date(displayDeparture).toISOString(), originZone, this.displayLocale))}` : "Date unavailable"}</div><div class="endpoint-code">${esc(origin)}${originCity ? ` · ${originCity}` : ""}</div></div>
          <div class="route-arrow" aria-hidden="true">✈</div>
          <div class="endpoint"><div class="endpoint-label">${arrivalLabel}</div><div class="endpoint-time" style="color:${arrivalTimeColor}">${displayArrival ? esc(airportTime(new Date(displayArrival).toISOString(), destinationZone, this.displayLocale)) : "Not entered"}</div><div class="airport-date">${displayArrival ? `${esc(airportDate(new Date(displayArrival).toISOString(), destinationZone, this.displayLocale))} · ${esc(airportZoneName(new Date(displayArrival).toISOString(), destinationZone, this.displayLocale))}` : "Enter an arrival date and time"}</div><div class="endpoint-code">${esc(destination)}${destinationCity ? ` · ${destinationCity}` : ""}</div></div>
        </div>
        <div class="schedule-progress">
          ${progress == null ? "" : `<div class="progress-track" role="progressbar" aria-label="${liveProgress != null ? "Live flight progress" : estimatedDeparture || estimatedArrival ? "Estimated flight progress" : "Scheduled flight progress"}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(progress)}" aria-valuetext="${esc(progressLabel)}"><div class="progress-fill" style="width:${progress}%;background:${progressColor}"></div><span class="progress-marker" style="left:${progress}%;background:${progressColor}"></span></div>`}
          <div class="progress-labels">${progress == null ? `<span class="progress-label centered">${esc(progressLabel)}</span>` : `<span class="progress-label" style="left:${progress}%;transform:translateX(${progress <= 8 ? "0" : progress >= 92 ? "-100%" : "-50%"})">${esc(progressLabel)}</span>`}</div>
          <div class="muted schedule-note">${hasArrived ? "Gate arrival confirmed by FR24." : isLanded ? "Landing confirmed; awaiting final gate confirmation." : liveProgress != null ? "Progress uses the recent aircraft position; displayed times use live data when available." : liveTracked ? "FR24 matched a live flight, but its position is unavailable or stale; the bar uses the saved schedule." : tracked ? "FR24 matched this scheduled flight. Updated estimated times are shown when available; aircraft position is not live yet." : "Schedule-based only; no matching FR24 flight record was found."}</div>
        </div>
        <details class="flight-details"><summary>Flight details</summary><div class="flight-detail-grid"><div><span class="muted">Scheduled departure airport time</span><strong>${esc(formatClock(dep.utc_timestamp, originZone, this.displayLocale))}</strong></div><div><span class="muted">Scheduled arrival airport time</span><strong>${esc(formatClock(arr.utc_timestamp, destinationZone, this.displayLocale))}</strong></div><div><span class="muted">Scheduled flight time</span><strong>${durationSeconds == null ? "Arrival not entered" : duration(durationSeconds)}</strong></div>${showElapsed ? `<div><span class="muted">${elapsedLabel}</span><strong>${elapsedValue}</strong></div>` : ""}<div><span class="muted">Now at ${esc(origin)}</span><strong>${esc(currentAirportTime(originZone, this.displayLocale))}</strong></div><div><span class="muted">Now at ${esc(destination)}</span><strong>${esc(currentAirportTime(destinationZone, this.displayLocale))}</strong></div>${liveTracked ? `<div><span class="muted">Now at aircraft</span><strong>${esc(this.renderPlaneClock(liveTracked, now))}</strong></div><div><span class="muted">Aircraft</span><strong>${esc(liveTracked.aircraft_registration || "FR24")}${liveTracked.altitude != null ? ` · ${esc(Math.round(Number(liveTracked.altitude)))} ft` : ""}${liveTracked.ground_speed != null ? ` · ${esc(Math.round(Number(liveTracked.ground_speed)))} kt` : ""}</strong></div>` : ""}</div></details>
      </div>
    </article>`;
  }

  renderPlaneClock(tracked, now) {
    const updated = stamp(tracked.position_updated_at);
    const fresh = isFreshUpdate(updated, now);
    const label = !fresh ? "Position unavailable or stale"
      : tracked.plane_timezone ? currentAirportTime(tracked.plane_timezone, this.displayLocale)
      : "Aircraft timezone unavailable";
    return label;
  }
}

class AirportItineraryEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._config = {};
    this._hass = null;
    this._form = null;
    this._formListener = (event) => this._handleFormChange(event);
  }

  setConfig(config) {
    const changed = JSON.stringify(this._config) !== JSON.stringify(config);
    this._config = { ...config };
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this.shadowRoot.innerHTML = `
        <style>
          :host { display:block; }
          ha-form { display:block; }
          .helper { color:var(--secondary-text-color); font-size:.9em; padding:0 16px 12px; }
        </style>
        <ha-form></ha-form>
        ${this.isSchedule ? '<div class="helper">Color fields accept CSS colors and Home Assistant variables such as var(--info-color).</div>' : ""}`;
      this._form = this.shadowRoot.querySelector("ha-form");
      this._form.addEventListener("value-changed", this._formListener);
    }
    if (changed || !this._form.data) this._form.data = this._formData();
    this._updateForm();
  }

  set hass(value) {
    this._hass = value;
    this._updateForm();
  }

  get hass() {
    return this._hass;
  }

  _formData() {
    const data = {
      entity: DEFAULT_ENTITY,
      title: this.isSchedule ? "Itinerary" : "Add a flight",
      ...this._config,
    };
    if (this.isSchedule) {
      data.show_fr24_connection_control ??= false;
      data.show_finish_flight_control ??= false;
      data.itinerary_id ??= "";
      data.status_colors = { ...(this._config.status_colors ?? {}) };
      data.airport_names = { ...(this._config.airport_names ?? {}) };
    } else {
      data.initial_fold ??= false;
      data.fold_empty_itineraries ??= true;
    }
    return data;
  }

  _itineraryOptions() {
    const states = Object.values(this._hass?.states ?? {});
    const configured = this._hass?.states?.[this._config.entity || DEFAULT_ENTITY];
    const source = Array.isArray(configured?.attributes?.itineraries)
      ? configured
      : states.find((state) => Array.isArray(state.attributes?.itineraries));
    return [
      { value: "", label: "All itineraries" },
      ...sortItineraries(source?.attributes?.itineraries ?? []).map((trip) => ({
        value: trip.id,
        label: trip.name || trip.id,
      })),
    ];
  }

  _schema() {
    const schema = [
      { name: "entity", required: true, selector: { entity: { filter: { domain: "sensor" } } } },
      { name: "title", selector: { text: {} } },
    ];
    if (!this.isSchedule) {
      schema.push(
        { name: "initial_fold", selector: { boolean: {} } },
        { name: "fold_empty_itineraries", selector: { boolean: {} } },
      );
      return schema;
    }
    schema.push(
      { name: "show_fr24_connection_control", selector: { boolean: {} } },
      { name: "show_finish_flight_control", selector: { boolean: {} } },
      { name: "itinerary_id", selector: { select: { mode: "dropdown", custom_value: true, options: this._itineraryOptions() } } },
      { name: "header_background", selector: { text: {} } },
      { name: "header_background_opacity", selector: { number: { min: 0, max: 100, step: 1, mode: "slider" } } },
      { name: "progress_color", selector: { text: {} } },
      { name: "finished_color", selector: { text: {} } },
      { name: "finish_delay_seconds", selector: { number: { min: 0, step: 1, mode: "box" } } },
      { name: "auto_collapse_after_minutes", selector: { number: { min: 0, step: 1, mode: "box" } } },
      {
        type: "expandable",
        name: "status_colors",
        title: "Flight status colors",
        flatten: false,
        schema: Object.keys(STATUS_COLOR_CONFIG).map((key) => ({ name: key, selector: { text: {} } })),
      },
      { name: "airport_names", selector: { object: {} } },
    );
    return schema;
  }

  _computeLabel(schema) {
    const labels = {
      entity: "Itinerary sensor",
      title: "Card title",
      initial_fold: "Start with the card collapsed",
      fold_empty_itineraries: "Fold flight fields until an itinerary is selected",
      itinerary_id: "Itinerary (optional)",
      show_fr24_connection_control: "Show FR24 connection control",
      show_finish_flight_control: "Show Finish flight control",
      header_background: "Header background color",
      header_background_opacity: "Header background opacity (%)",
      progress_color: "Progress color",
      finished_color: "Finished color",
      finish_delay_seconds: "Finish delay (seconds)",
      auto_collapse_after_minutes: "Auto-collapse delay (minutes)",
      airport_names: "Airport code to display name overrides",
      scheduled: "Scheduled",
      in_transit: "In transit",
      airborne: "Airborne",
      landed: "Landed",
      arrived: "Arrived",
      connection: "Connection",
      completed: "Completed",
    };
    return labels[schema.name] || schema.name;
  }

  _updateForm() {
    if (!this._form) return;
    this._form.hass = this._hass;
    this._form.schema = this._schema();
    this._form.computeLabel = (schema) => this._computeLabel(schema);
  }

  _handleFormChange(event) {
    event.stopPropagation();
    const values = event.detail?.value;
    if (!values || typeof values !== "object") return;
    const config = { ...this._config, ...values };
    if (this.isSchedule) {
      config.status_colors = { ...(this._config.status_colors ?? {}), ...(values.status_colors ?? {}) };
      config.airport_names = { ...(values.airport_names ?? {}) };
    }
    this._config = config;
    this.dispatchEvent(new CustomEvent("config-changed", {
      detail: { config },
      bubbles: true,
      composed: true,
    }));
  }
}

class AirportItineraryInputEditor extends AirportItineraryEditor {
  get isSchedule() { return false; }
}

class AirportItineraryScheduleEditor extends AirportItineraryEditor {
  get isSchedule() { return true; }
}

for (const [name, element] of [
  ["airport-itinerary-input", AirportItineraryInput],
  ["airport-itinerary-schedule", AirportItinerarySchedule],
  ["airport-itinerary-input-editor", AirportItineraryInputEditor],
  ["airport-itinerary-schedule-editor", AirportItineraryScheduleEditor],
]) {
  if (!customElements.get(name)) customElements.define(name, element);
}

window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === "airport-itinerary-input")) window.customCards.push({
  type: "airport-itinerary-input",
  name: "Airport Itinerary Input",
  description: "Create itineraries and add airport-local flight schedules.",
  preview: false,
  getStubConfig: () => ({
    type: "custom:airport-itinerary-input",
    entity: DEFAULT_ENTITY,
    title: "Add a flight",
  }),
});
if (!window.customCards.some(card => card.type === "airport-itinerary-schedule")) window.customCards.push({
  type: "airport-itinerary-schedule",
  name: "Airport Itinerary Reservations",
  description: "Reservation-style flight schedule with airport clocks and travel times.",
  preview: false,
  getStubConfig: () => ({
    type: "custom:airport-itinerary-schedule",
    entity: DEFAULT_ENTITY,
    title: "Itinerary",
  }),
});
console.info(`%c AIRPORT-ITINERARY %c ${CARD_VERSION} `, "color:#fff;background:#1677a8;font-weight:bold", "color:#1677a8;font-weight:bold");
