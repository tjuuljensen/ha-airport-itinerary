const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

class TestCustomEvent {
  constructor(type, options = {}) {
    this.type = type;
    this.detail = options.detail;
  }
}

class TestElement {
  constructor() {
    this.events = [];
    this.attachShadow = () => {
      const root = {
        form: null,
        querySelector(selector) {
          return selector === "ha-form" ? this.form : null;
        },
        set innerHTML(value) {
          this.form = new TestForm();
        },
      };
      this.shadowRoot = root;
      return root;
    };
  }

  dispatchEvent(event) {
    this.events.push(event);
    return true;
  }
}

class TestForm {
  constructor() {
    this.listeners = {};
  }

  addEventListener(name, callback) {
    this.listeners[name] = callback;
  }
}

const loadCard = () => {
  const definitions = new Map();
  const context = {
    HTMLElement: TestElement,
    CustomEvent: TestCustomEvent,
    customElements: { get: (name) => definitions.get(name), define: (name, element) => definitions.set(name, element) },
    document: { createElement: (name) => ({ tagName: name }) },
    window: { customCards: [] },
    console: { info() {} },
    navigator: { language: "en" },
  };
  const source = fs.readFileSync(path.join(__dirname, "custom_components/airport_aware_itinerary/www/airport-itinerary.js"), "utf8");
  vm.runInNewContext(`${source}\nglobalThis.__testApi = { routeProgress, AirportItinerarySchedule, sortItineraries, waitingForFlightDetails, preferredItinerary, isFreshUpdate };`, context);
  return { ...context, definitions, api: context.__testApi };
};

test("route progress follows and clamps to the great-circle route", () => {
  const { api } = loadCard();
  const origin = { latitude: 0, longitude: 0 };
  const destination = { latitude: 0, longitude: 10 };

  assert.ok(Math.abs(api.routeProgress(origin, destination, { latitude: 0, longitude: 5 }) - 50) < 0.01);
  assert.equal(api.routeProgress(origin, destination, { latitude: 0, longitude: -1 }), 0);
  assert.equal(api.routeProgress(origin, destination, { latitude: 0, longitude: 11 }), 100);
  assert.equal(api.routeProgress(origin, destination, { latitude: 100, longitude: 0 }), null);
  assert.equal(api.routeProgress(origin, destination, null), null);
});

test("scheduled FR24 matches show fresh estimated times without live position status", () => {
  const { api } = loadCard();
  const card = Object.create(api.AirportItinerarySchedule.prototype);
  card._config = {};
  card._legCollapseOverrides = new Map();
  card._hass = { locale: { language: "en-US" } };
  const now = Date.parse("2026-10-23T12:00:00Z");
  const trip = {
    id: "trip-1",
    legs: [{ id: "leg-1" }],
  };
  const leg = {
    id: "leg-1",
    flight_number: "UA760",
    origin_airport: "DEN",
    destination_airport: "MUC",
    departure: { utc_timestamp: "2026-10-23T20:00:00Z", timezone: "America/Denver" },
    arrival: { utc_timestamp: "2026-10-24T12:00:00Z", timezone: "Europe/Berlin" },
  };
  const tracked = [{
    itinerary_id: "trip-1",
    leg_id: "leg-1",
    is_live: false,
    tracked_type: "scheduled",
    position_updated_at: new Date(now - 60_000).toISOString(),
    time_estimated_departure: "2026-10-23T22:00:00Z",
    time_estimated_arrival: "2026-10-24T14:30:00Z",
  }];

  const html = card.renderLeg(trip, leg, 0, tracked, now);

  assert.match(html, /Estimated departure/);
  assert.match(html, /Estimated arrival/);
  assert.match(html, /FR24 matched this scheduled flight/);
  assert.match(html, /aria-label="Estimated flight progress"/);
  assert.doesNotMatch(html, /Live position/);
});

test("both cards register visual editors", () => {
  const { definitions } = loadCard();

  assert.equal(
    definitions.get("airport-itinerary-input").getConfigElement().tagName,
    "airport-itinerary-input-editor",
  );
  assert.equal(
    definitions.get("airport-itinerary-schedule").getConfigElement().tagName,
    "airport-itinerary-schedule-editor",
  );
});

test("input editor exposes its entity and title settings", () => {
  const { definitions } = loadCard();
  const Editor = definitions.get("airport-itinerary-input-editor");
  const editor = new Editor();
  editor.setConfig({ entity: "sensor.flight_itineraries", title: "Add a flight" });

  assert.deepEqual(Array.from(editor._form.schema, (field) => field.name), ["entity", "title", "initial_fold", "fold_empty_itineraries"]);
});

test("schedule editor exposes all supported options and preserves unknown config", () => {
  const { definitions } = loadCard();
  const Editor = definitions.get("airport-itinerary-schedule-editor");
  const editor = new Editor();
  editor.setConfig({
    entity: "sensor.flight_itineraries",
    title: "Trip",
    custom_existing_setting: "keep-me",
    status_colors: { custom_status: "purple" },
    airport_names: { CPH: "Copenhagen" },
  });
  const names = editor._form.schema.flatMap((field) => [
    field.name,
    ...(field.schema?.map((item) => item.name) ?? []),
  ]);
  for (const name of [
    "entity", "title", "itinerary_id", "header_background",
    "header_background_opacity", "progress_color", "finished_color",
    "finish_delay_seconds", "auto_collapse_after_minutes", "status_colors",
    "airport_names", "show_fr24_connection_control", "show_finish_flight_control",
  ]) {
    assert.ok(names.includes(name), `missing editor setting: ${name}`);
  }
  assert.equal(editor._form.data.show_fr24_connection_control, false);
  assert.equal(editor._form.data.show_finish_flight_control, false);

  editor._form.listeners["value-changed"]({
    stopPropagation() {},
    detail: {
      value: {
        title: "Updated",
        show_fr24_connection_control: true,
        show_finish_flight_control: true,
        status_colors: { scheduled: "var(--primary-text-color)" },
        airport_names: { LAX: "Los Angeles" },
      },
    },
  });
  const config = editor.events.at(-1).detail.config;
  assert.equal(config.show_fr24_connection_control, true);
  assert.equal(config.show_finish_flight_control, true);
  assert.equal(config.custom_existing_setting, "keep-me");
  assert.equal(config.status_colors.custom_status, "purple");
  assert.equal(config.status_colors.scheduled, "var(--primary-text-color)");
  assert.equal(config.airport_names.CPH, undefined);
  assert.equal(config.airport_names.LAX, "Los Angeles");
});


test("itineraries sort earliest departure first without mutating source", () => {
  const { api } = loadCard();
  const leg = (date) => ({ departure: { utc_timestamp: date } });
  const trips = [
    { id: "empty", legs: [] },
    { id: "older", legs: [leg("2026-11-20T10:00:00Z"), leg("2026-10-01T10:00:00Z")] },
    { id: "newest", legs: [leg("2026-11-01T12:00:00+02:00")] },
    { id: "tie", legs: [leg("2026-11-01T10:00:00Z")] },
    { id: "invalid", legs: [leg("not a date")] },
  ];
  const original = JSON.stringify(trips);
  assert.deepEqual(Array.from(api.sortItineraries(trips), x => x.id), ["older", "newest", "tie", "empty", "invalid"]);
  assert.equal(JSON.stringify(trips), original);
});

test("waiting details requires a compatible number-only scheduled watch", () => {
  const { api } = loadCard();
  const leg = { flight_number: "MS0760", origin_airport: "CPH", destination_airport: "CAI" };
  const watch = { flight_number: "MS760", tracked_type: "schedule" };
  assert.equal(api.waitingForFlightDetails([leg], [watch]), true);
  for (const change of [{ flight_number: "MS761" }, { airport_origin_code_iata: "CAI" },
    { airport_destination_code_iata: "LHR" }, { tracked_type: "live" },
    { time_scheduled_departure: "2026-10-31T14:05:00Z" }]) {
    assert.equal(api.waitingForFlightDetails([leg], [{ ...watch, ...change }]), false);
  }
  assert.equal(api.waitingForFlightDetails([{ ...leg, completed: true }], [watch]), false);
  assert.equal(api.waitingForFlightDetails([leg], []), false);
  assert.equal(api.waitingForFlightDetails([leg], undefined), false);
});


test("default itinerary selection prefers active then nearest upcoming journeys", () => {
  const { api } = loadCard();
  const now = Date.parse('2026-10-31T12:00:00Z');
  const iso = offset => new Date(now + offset * 3600000).toISOString();
  const trips = ['latest', 'next', 'active', 'past'].map(id => ({ id, legs: [] }));
  const journeys = [
    { itinerary_id: 'latest', departure_at: iso(48), expires_at: iso(50) },
    { itinerary_id: 'next', departure_at: iso(2), expires_at: iso(4) },
    { itinerary_id: 'active', departure_at: iso(-1), expires_at: iso(1) },
    { itinerary_id: 'past', departure_at: iso(-10), expires_at: iso(-8) },
  ];
  assert.equal(api.preferredItinerary(trips, journeys, now).id, 'active');
  assert.equal(api.preferredItinerary(trips, journeys, now + 3600000).id, 'next');
  journeys[2].completed = true;
  assert.equal(api.preferredItinerary(trips, journeys, now).id, 'next');
  journeys[2].final_arrival_at = iso(0);
  assert.equal(api.preferredItinerary(trips, journeys, now).id, 'active');
  assert.equal(api.preferredItinerary(trips, journeys, now + 300000).id, 'next');
  assert.equal(api.preferredItinerary(trips, journeys, now + 300000, 600).id, 'active');
  delete journeys[2].final_arrival_at;
  journeys[2].completed = false;
  journeys[2].expires_at = iso(-0.5);
  journeys[2].airborne = true;
  assert.equal(api.preferredItinerary(trips, journeys, now).id, 'active');
  assert.equal(api.preferredItinerary(trips.filter(t => t.id !== 'active'), journeys, now).id, 'next');
  assert.equal(api.preferredItinerary([], journeys, now), undefined);
  assert.equal(api.preferredItinerary(trips, [], now).id, 'latest');
});

test("selection uses a later journey in the same trip and supports schedule-only fallback", () => {
  const { api } = loadCard();
  const now = Date.parse('2026-10-31T12:00:00Z');
  const trips = [{ id: 'later', legs: [] }, { id: 'return', legs: [] }];
  const journeys = [
    { itinerary_id: 'later', departure_at: '2026-11-10T12:00:00Z' },
    { itinerary_id: 'return', departure_at: '2026-10-01T12:00:00Z', completed: true },
    { itinerary_id: 'return', departure_at: '2026-11-01T12:00:00Z' },
  ];
  assert.equal(api.preferredItinerary(trips, journeys, now).id, 'return');
  trips[1].legs = [{ departure: { utc_timestamp: '2026-10-31T11:00:00Z' }, arrival: { utc_timestamp: '2026-10-31T13:00:00Z' } }];
  assert.equal(api.preferredItinerary(trips, [], now).id, 'return');
  trips[1].legs[0].completed = true;
  assert.equal(api.preferredItinerary(trips, [], now).id, 'later');
});


test("live ground status is distinct from scheduled, airborne and completed", () => {
  const { api } = loadCard();
  const card = Object.create(api.AirportItinerarySchedule.prototype);
  card._config = {}; card._legCollapseOverrides = new Map(); card._hass = { locale: { language: 'en-GB' } };
  const now = Date.parse('2026-10-31T14:30:00Z');
  const leg = { id: 'leg', flight_number: 'MS760', origin_airport: 'CPH', destination_airport: 'CAI',
    departure: { utc_timestamp: '2026-10-31T14:05:00Z', timezone: 'Europe/Copenhagen' },
    arrival: { utc_timestamp: '2026-10-31T18:30:00Z', timezone: 'Africa/Cairo' } };
  const trip = { id: 'trip', legs: [leg] };
  const live = { itinerary_id: 'trip', leg_id: 'leg', is_live: true, on_ground: true, position_updated_at: new Date(now).toISOString() };
  const status = (tracking, row=leg) => card.renderLeg(trip, row, 0, tracking, now).match(/<span class="badge"[^>]*>(.*?)<\/span>/)[1];
  assert.equal(status([live]), 'On ground');
  assert.equal(status([{ ...live, on_ground: false }]), 'Airborne');
  assert.equal(status([]), 'Scheduled');
  assert.equal(status([{ ...live, is_live: false }]), 'Scheduled');
  assert.equal(status([{ ...live, position_updated_at: new Date(now - 301000).toISOString() }]), 'Scheduled');
  assert.equal(status([{ ...live, time_real_landing: now / 1000 }]), 'Landed · awaiting gate');
  assert.equal(status([{ ...live, time_real_arrival: now / 1000 }]), 'Landed · awaiting gate');
  assert.equal(status([{ ...live, gate_arrived_sent: true }]), 'Final arrival · at gate');
  assert.equal(status([live], { ...leg, completed: true, evidence: { manual_completion: true } }), 'Completed manually');
  const delayed = { ...leg, arrival: { ...leg.arrival, utc_timestamp: '2026-10-31T13:00:00Z' } };
  assert.equal(status([live], delayed), 'On ground');
  assert.equal(card.getFinishedAt({ ...trip, legs: [delayed] }, [live], now), null);
});


test("freshness tolerates bounded server clock skew without extending stale data", () => {
  const { api } = loadCard();
  const now=Date.parse('2026-10-31T14:50:00Z');
  for(const offset of [-300000, -1000, 0, 750, 15000, 60000]) assert.equal(api.isFreshUpdate(now+offset,now), true);
  for(const offset of [-300001, 60001]) assert.equal(api.isFreshUpdate(now+offset,now), false);
  assert.equal(api.isFreshUpdate(null,now),false);
  const card=Object.create(api.AirportItinerarySchedule.prototype);card._config={};card._legCollapseOverrides=new Map();card._hass={locale:{language:'en-GB'}};
  const leg={id:'leg',flight_number:'MS760',departure:{utc_timestamp:'2026-10-31T12:00:00Z',timezone:'UTC'},arrival:{utc_timestamp:'2026-10-31T14:00:00Z',timezone:'UTC'}};
  const trip={id:'trip',legs:[leg]};
  const tracked=[{itinerary_id:'trip',leg_id:'leg',is_live:true,on_ground:false,time_real_departure:now/1000-3600,position_updated_at:new Date(now+750).toISOString()}];
  assert.ok(card.renderLeg(trip,leg,0,tracked,now).includes(">Airborne</span>"));
  assert.equal(card.getFinishedAt(trip,tracked,now),null);
});

test("landing stays coloured and expanded until the final gate arrival timer", () => {
  const { api } = loadCard();
  const card = Object.create(api.AirportItinerarySchedule.prototype);
  card._config = { finish_delay_seconds: 300, auto_collapse_after_minutes: 1, finished_color: '#aabbcc' };
  card._legCollapseOverrides = new Map(); card._hass = { locale: { language: 'en-GB' } };
  const now = Date.parse('2026-10-31T18:30:00Z');
  const landing = new Date(now - 1800000).toISOString();
  const leg = { id: 'leg', flight_number: 'MS760', finished_at: landing,
    departure: { utc_timestamp: '2026-10-31T13:00:00Z', timezone: 'UTC' },
    arrival: { utc_timestamp: '2026-10-31T18:00:00Z', timezone: 'UTC' },
    evidence: { actual_arrival: landing, touchdown: landing } };
  const trip = { id: 'trip', legs: [leg] };
  const live = { itinerary_id: 'trip', leg_id: 'leg', is_live: true, on_ground: true,
    has_landed: true, gate_arrived_sent: false, ground_speed: 12, position_updated_at: new Date(now).toISOString() };
  let html = card.renderLeg(trip, leg, 0, [live], now);
  assert.match(html, />Taxiing to gate<\/span>/);
  assert.match(html, /background:var\(--airport-itinerary-status-landed\)/);
  assert.doesNotMatch(html, /class="leg [^"]*(finished|finishing|completed)/);
  assert.doesNotMatch(html, /class="leg-body" hidden/);
  assert.equal(card.getFinishedAt(trip, [live], now), null);
  // Loss of tracking and old finished_at values cannot promote landing to final arrival.
  html = card.renderLeg(trip, leg, 0, [], now);
  assert.match(html, /Landed · awaiting gate/);
  assert.match(html, /background:var\(--airport-itinerary-status-landed\)/);
  assert.equal(card.getFinishedAt(trip, [], now), null);
  html = card.renderLeg(trip, leg, 0, [{ ...live, position_updated_at: landing }], now);
  assert.doesNotMatch(html, /Taxiing to gate/);
  for (const invalid of ['false', 'true', false, 1]) {
    html = card.renderLeg(trip, leg, 0, [{ ...live, gate_arrived_sent: invalid }], now);
    assert.doesNotMatch(html, /Final arrival · at gate/);
  }
  const manual = { ...leg, completed: true, evidence: { ...leg.evidence, manual_completion: new Date(now).toISOString() } };
  html = card.renderLeg(trip, manual, 0, [live], now);
  assert.match(html, /Completed manually/);
  assert.doesNotMatch(html, /Taxiing to gate|Landed · awaiting gate/);
  leg.evidence.gate_arrival = new Date(now).toISOString();
  html = card.renderLeg(trip, leg, 0, [], now);
  assert.match(html, /Final arrival · at gate/);
  assert.match(html, /background:var\(--airport-itinerary-status-arrived\)/);
  assert.equal(card.getFinishedAt(trip, [], now), now + 300000);
  html = card.renderLeg(trip, leg, 0, [], now + 299999);
  assert.doesNotMatch(html, /background:var\(--airport-itinerary-finished-color/);
  html = card.renderLeg(trip, leg, 0, [], now + 300000);
  assert.match(html, /background:var\(--airport-itinerary-finished-color/);
  assert.doesNotMatch(html, /class="leg-body" hidden/);
  html = card.renderLeg(trip, leg, 0, [], now + 360000);
  assert.match(html, /class="leg-body" hidden/);
});
