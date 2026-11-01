const { test, expect } = require('@playwright/test');
const path = require('node:path');

async function mount(page, width = 490) {
  await page.setViewportSize({ width: 1000, height: 1200 });
  await page.setContent(`<style>body{font:14px Arial;background:#182c24;color:white}airport-itinerary-input,airport-itinerary-schedule{width:${width}px;--primary-text-color:white;--secondary-text-color:#ddd;--primary-background-color:#303030;--ha-card-background:#29483b;--primary-color:#ff9800;--text-primary-color:white}</style>`);
  await page.addScriptTag({ path: path.resolve(__dirname, '../custom_components/airport_aware_itinerary/www/airport-itinerary.js') });
  await page.evaluate(() => {
    window.calls = [];
    window.fail = false;
    const trip = { id: 'trip', name: 'Outbound', legs: [] };
    window.hass = {
      locale: { language: 'en-GB' },
      states: { 'sensor.flight_itineraries': { entity_id: 'sensor.flight_itineraries', attributes: { itineraries: [trip] } } },
      services: { airport_aware_itinerary: { create_itinerary: {}, add_flight: {}, rename_itinerary: {} } },
      async callService(domain, service, data) {
        window.calls.push({ service, data });
        await new Promise(resolve => setTimeout(resolve, 30));
        if (window.fail) return { success: false, error: 'Test validation error' };
        if (service === 'add_flight') return { success: true, itinerary: { ...trip, legs: [{ id: 'leg', ...data }] } };
        if (service === 'create_itinerary') return { success: true, itinerary: { id: 'return', name: data.name, legs: [] } };
        return { success: true, itinerary: { ...trip, name: data.name } };
      },
    };
    window.card = document.createElement('airport-itinerary-input');
    card.setConfig({ type: 'custom:airport-itinerary-input' });
    document.body.append(card);
    card.hass = hass;
  });
}

async function fillFlight(page) {
  await page.locator('#number').fill('SK935');
  await page.locator('#origin').fill('CPH');
  await page.locator('#destination').fill('LAX');
  await page.locator('#date').fill('2026-11-01');
  await page.locator('#departure').fill('12:30');
}

test('suggested arrival is omitted without a time and repeated clicks save once', async ({ page }) => {
  await mount(page);
  await fillFlight(page);
  await expect(page.locator('#arrival-date')).toHaveValue('2026-11-01');
  await page.evaluate(() => {
    const form = card.shadowRoot.querySelector('#flight-form');
    form.requestSubmit(); form.requestSubmit();
  });
  await expect(page.locator('.notice')).toHaveText('Flight added.');
  const calls = await page.evaluate(() => window.calls);
  expect(calls).toHaveLength(1);
  expect(calls[0].data.arrival_date).toBeUndefined();
});

test('manual arrival dates and cleared dates survive departure edits and folding', async ({ page }) => {
  await mount(page);
  await fillFlight(page);
  await page.locator('#arrival-date').fill('2026-11-02');
  await page.locator('#date').fill('2026-11-03');
  await expect(page.locator('#arrival-date')).toHaveValue('2026-11-02');
  await page.locator('#arrival-date').fill('');
  await page.locator('#toggle-input-collapse').click();
  await page.locator('#toggle-input-collapse').click();
  await page.locator('#date').fill('2026-11-04');
  await expect(page.locator('#arrival-date')).toHaveValue('');
  await expect(page.locator('#number')).toHaveValue('SK935');
});

test('failed saves and name editing preserve flight drafts', async ({ page }) => {
  await mount(page);
  await fillFlight(page);
  await page.locator('#edit-itinerary').click();
  await page.locator('#cancel-name-edit').click();
  await page.evaluate(() => { window.fail = true; });
  await page.getByRole('button', { name: 'Add flight to itinerary', exact: true }).click();
  await expect(page.locator('.notice')).toHaveText('Test validation error');
  await expect(page.locator('#number')).toHaveValue('SK935');
  await expect(page.locator('#departure')).toHaveValue('12:30');
  await page.evaluate(() => { hass.states['sensor.flight_itineraries'].attributes.itineraries[0].name = 'Updated'; card.hass = { ...hass }; });
  await expect(page.locator('#number')).toHaveValue('SK935');
});

test('return is an unsaved reversed draft and cancellation creates no trip', async ({ page }) => {
  await mount(page);
  await fillFlight(page);
  await page.getByRole('button', { name: 'Add + prepare return', exact: true }).click();
  await expect(page.locator('#new-name')).toHaveValue('LAX-CPH');
  await expect(page.locator('#origin')).toHaveValue('LAX');
  await expect(page.locator('#destination')).toHaveValue('CPH');
  await expect(page.locator('#number')).toHaveValue('');
  await expect(page.locator('#departure')).toHaveValue('');
  await expect(page.locator('#trip')).toHaveValue('');
  await page.locator('#cancel-name-edit').click();
  expect(await page.evaluate(() => window.calls.map(call => call.service))).toEqual(['add_flight']);
});

test('explicit return creation preserves reversed form and independent folds', async ({ page }) => {
  await mount(page);
  await fillFlight(page);
  await page.getByRole('button', { name: 'Add + prepare return', exact: true }).click();
  await page.getByRole('button', { name: 'Create itinerary', exact: true }).last().click();
  await expect(page.locator('#trip')).toHaveValue('return');
  await expect(page.locator('#origin')).toHaveValue('LAX');
  await page.locator('#fold').selectOption('earlier');
  await page.locator('#arrival-fold').selectOption('later');
  await expect(page.locator('#fold')).toHaveValue('earlier');
  await expect(page.locator('#arrival-fold')).toHaveValue('later');
});

for (const width of [320, 390, 490]) {
  test(`native fields fit and align at card width ${width}`, async ({ page }) => {
    await mount(page, width);
    await fillFlight(page);
    if (width === 390) await page.setViewportSize({ width: 406, height: 1200 });
    const boxes = await page.locator('#flight-form input').evaluateAll(inputs => inputs.map(input => {
      const r = input.getBoundingClientRect(); const field = input.parentElement.getBoundingClientRect();
      return { left: r.left, right: r.right, width: r.width, top: r.top, parentRight: field.right };
    }));
    expect(boxes.every(box => box.width > 0 && box.right <= box.parentRight + 1)).toBeTruthy();
    if (width < 420) expect(new Set(boxes.map(box => box.left)).size).toBe(1);
    else expect(boxes[6].top).toBe(boxes[7].top);
    await page.screenshot({ path: `test-results/input-${width}.png`, fullPage: true });
  });
}

test('tracking notices update when only controller state changes', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({});
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.tracking_source_health = 'no_flights';
    attrs.tracking = { fetching: false, auto_track: true };
    attrs.journeys = [{ itinerary_id: 'trip', api_start_at: new Date(Date.now() + 3600000).toISOString(), tracking_required: false }];
    document.body.append(schedule); schedule.hass = hass;
  });
  await expect(page.locator('.tracking-notice')).toContainText('Tracking starts');
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.journeys = [{ itinerary_id: 'trip', tracking_required: true }];
    schedule.hass = { ...hass };
  });
  await expect(page.locator('.tracking-notice')).toContainText('fetching is off');
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.tracking.fetching = true;
    schedule.hass = { ...hass };
  });
  await expect(page.locator('.tracking-notice')).toContainText('Waiting for FR24');
});

test('manual completion is opt-in and still requires confirmation', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();
    hass.services.airport_aware_itinerary.mark_flight_completed = {};
    hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs = [{
      id: 'leg', flight_number: 'SK935', origin_airport: 'CPH', destination_airport: 'LAX',
      departure: { utc_timestamp: '2026-11-01T11:30:00+00:00', timezone: 'Europe/Copenhagen' },
    }];
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({}); document.body.append(schedule); schedule.hass = hass;
  });
  const finish = page.getByRole('button', { name: 'Mark SK935 completed', exact: true });
  await expect(finish).toHaveCount(0);
  await page.evaluate(() => schedule.setConfig({ show_finish_flight_control: false }));
  await expect(finish).toHaveCount(0);
  await page.evaluate(() => schedule.setConfig({ show_finish_flight_control: 'true' }));
  await expect(finish).toHaveCount(0);
  expect(await page.evaluate(() => calls.length)).toBe(0);
  await page.evaluate(() => schedule.setConfig({ show_finish_flight_control: true }));
  await expect(finish).toHaveCount(1);
  page.once('dialog', dialog => dialog.dismiss());
  await page.getByRole('button', { name: 'Mark SK935 completed', exact: true }).click();
  expect(await page.evaluate(() => window.calls.length)).toBe(0);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Mark SK935 completed', exact: true }).click();
  await expect(page.locator('.notice')).toHaveText('Flight manually completed.');
  expect(await page.evaluate(() => window.calls[0])).toEqual({ service: 'mark_flight_completed', data: { itinerary_id: 'trip', leg_id: 'leg' } });
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs[0].completed = true;
    schedule.hass = { ...hass };
  });
  await expect(finish).toHaveCount(0);
  await page.evaluate(() => schedule.setConfig({ show_finish_flight_control: false }));
  await expect(finish).toHaveCount(0);
  expect(await page.evaluate(() => calls.length)).toBe(1);
});

test('FR24 connection toggles mode without changing drafts or settings', async ({ page }) => {
  await mount(page);
  await fillFlight(page);
  await page.evaluate(() => {
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.fr24_connection_entity = 'switch.airport_itinerary_fr24_connection';
    attrs.tracking = { connection_enabled: true };
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({}); document.body.append(schedule); schedule.hass = hass;
    hass.callService = async (domain, service, data) => {
      calls.push({ domain, service, data });
      await new Promise(resolve => setTimeout(resolve, 50));
      if (window.fail) throw new Error('Unable to change connection');
      attrs.tracking.connection_enabled = service === 'turn_on';
      attrs.tracking_source_health = service === 'turn_on' ? 'no_flights' : 'disabled';
      schedule.hass = { ...hass };
    };
  });
  const toggle = page.getByRole('switch', { name: 'FR24 connection' });
  await expect(toggle).toHaveCount(0);
  expect(await page.evaluate(() => calls.length)).toBe(0);
  await page.evaluate(() => schedule.setConfig({ show_fr24_connection_control: true }));
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  await toggle.dblclick();
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await expect(page.locator('.tracking-notice')).toContainText('Schedule-only mode');
  await page.evaluate(() => { schedule.style.display = 'block'; schedule.style.width = '390px'; });
  await page.locator('airport-itinerary-schedule').screenshot({ path: 'test-results/schedule-only-390.png' });
  expect(await page.evaluate(() => calls)).toEqual([{ domain: 'switch', service: 'turn_off', data: { entity_id: 'switch.airport_itinerary_fr24_connection' } }]);
  await expect(page.locator('#number')).toHaveValue('SK935');
  await expect(page.locator('#date')).toHaveValue('2026-11-01');
  await page.evaluate(() => { window.fail = true; });
  await toggle.click();
  await expect(page.locator('airport-itinerary-schedule .notice')).toHaveText('Unable to change connection');
  await expect(toggle).toHaveAttribute('aria-checked', 'false');
  await page.evaluate(() => { window.fail = false; });
  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-checked', 'true');
  const callCount = await page.evaluate(() => calls.length);
  await page.evaluate(() => schedule.setConfig({ show_fr24_connection_control: false }));
  await expect(toggle).toHaveCount(0);
  expect(await page.evaluate(() => calls.length)).toBe(callCount);
});

test('loading the bundled module twice keeps one registration per card', async ({ page }) => {
  await mount(page);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addScriptTag({ type: 'module', path: path.resolve(__dirname, '../custom_components/airport_aware_itinerary/www/airport-itinerary.js') });
  await page.addScriptTag({ type: 'module', path: path.resolve(__dirname, '../custom_components/airport_aware_itinerary/www/airport-itinerary.js') });
  expect(await page.evaluate(() => window.customCards.filter(card => card.type.startsWith('airport-itinerary-')).length)).toBe(2);
  expect(errors).toEqual([]);
});


test('dropdowns sort by departure while preserving selections and drafts', async ({ page }) => {
  await mount(page);
  await fillFlight(page);
  await page.evaluate(() => {
    const dated = (id, date) => ({ id, name: id, legs: [{ id: id + '-leg', flight_number: 'MS760', departure: { utc_timestamp: date, timezone: 'UTC' } }] });
    hass.states['sensor.flight_itineraries'].attributes.itineraries = [
      dated('older', '2026-10-01T10:00:00Z'),
      { id: 'trip', name: 'Draft', legs: [] },
      dated('newest', '2026-11-01T10:00:00Z'),
    ];
    card.hass = { ...hass };
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({}); document.body.append(schedule); schedule.hass = hass;
    window.editor = document.createElement('airport-itinerary-schedule-editor');
    editor.setConfig({}); editor.hass = hass;
  });
  const input = page.locator('airport-itinerary-input #trip');
  const schedule = page.locator('airport-itinerary-schedule #trip');
  expect(await input.locator('option').evaluateAll(rows => rows.map(row => row.value))).toEqual(['', 'older', 'newest', 'trip']);
  expect(await schedule.locator('option').evaluateAll(rows => rows.map(row => row.value))).toEqual(['older', 'newest', 'trip']);
  expect(await page.evaluate(() => editor._itineraryOptions().map(row => row.value))).toEqual(['', 'older', 'newest', 'trip']);
  await expect(input).toHaveValue('trip');
  await expect(page.locator('#number')).toHaveValue('SK935');
  await schedule.selectOption('older');
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs[0].departure.utc_timestamp = '2026-12-01T10:00:00Z';
    card.hass = { ...hass }; schedule.hass = { ...hass };
    schedule.shadowRoot.activeElement?.blur(); schedule.render();
  });
  expect(await input.locator('option').evaluateAll(rows => rows.map(row => row.value))).toEqual(['', 'newest', 'older', 'trip']);
  await expect(input).toHaveValue('trip');
  await expect(schedule).toHaveValue('older');
  await expect(page.locator('#number')).toHaveValue('SK935');
});

test('accepted FR24 watch shows waiting details only for the selected flight', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries[0].legs = [{ id: 'leg', flight_number: 'MS760', origin_airport: 'CPH', destination_airport: 'CAI', departure: { utc_timestamp: '2026-10-31T14:05:00Z', timezone: 'UTC' } }];
    attrs.tracking_source_health = 'no_matching_flight';
    attrs.tracking_source_entity = 'sensor.fr24';
    attrs.tracking = { fetching: true, auto_track: true };
    hass.states['sensor.fr24'] = { attributes: { flights: [] } };
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({}); document.body.append(schedule); schedule.hass = hass;
  });
  await expect(page.locator('.tracking-notice')).toContainText('Waiting for FR24 to resolve');
  await page.evaluate(() => { hass.states['sensor.fr24'].attributes.flights = [{ flight_number: 'MS760', tracked_type: 'schedule' }]; schedule.hass = { ...hass }; });
  await expect(page.locator('.tracking-notice')).toHaveText('Added to FR24—waiting for flight details');
  await page.evaluate(() => { hass.states['sensor.fr24'].attributes.flights[0].flight_number = 'MS761'; schedule.hass = { ...hass }; });
  await expect(page.locator('.tracking-notice')).toContainText('Waiting for FR24 to resolve');
});


test('schedule defaults to active then upcoming without reordering or overriding manual choice', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();
    const now = Date.now();
    const iso = hours => new Date(now + hours * 3600000).toISOString();
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries = [
      { id: 'active', name: 'Active', legs: [{ id: 'a', departure: { utc_timestamp: iso(-1), timezone: 'UTC' } }] },
      { id: 'latest', name: 'Latest', legs: [{ id: 'l', departure: { utc_timestamp: iso(48), timezone: 'UTC' } }] },
      { id: 'next', name: 'Next', legs: [{ id: 'n', departure: { utc_timestamp: iso(2), timezone: 'UTC' } }] },
    ];
    attrs.journeys = attrs.itineraries.map(t => ({ itinerary_id: t.id, departure_at: t.legs[0].departure.utc_timestamp, expires_at: iso(t.id === 'active' ? 1 : 60) }));
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({}); document.body.append(schedule); schedule.hass = hass;
  });
  const select = page.locator('airport-itinerary-schedule #trip');
  await expect(select).toHaveValue('active');
  expect(await select.locator('option').evaluateAll(rows => rows.map(row => row.value))).toEqual(['active', 'next', 'latest']);
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.journeys[0].completed = true;
    schedule.hass = { ...hass };
  });
  await expect(select).toHaveValue('next');
  await select.selectOption('latest');
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.journeys[0].completed = false;
    schedule.shadowRoot.activeElement?.blur(); schedule.hass = { ...hass }; schedule.render();
  });
  await expect(select).toHaveValue('latest');
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.itineraries = hass.states['sensor.flight_itineraries'].attributes.itineraries.filter(t => t.id !== 'latest');
    schedule.hass = { ...hass };
  });
  await expect(select).toHaveValue('active');
  await page.evaluate(() => schedule.setConfig({ itinerary_id: 'next' }));
  await expect(select).toHaveCount(0);
  expect(await page.evaluate(() => schedule._selected)).toBe('next');
});

test('retained arrival replaces the waiting notice and stays selected after FR24 cleanup', async ({ page }, testInfo) => {
  await mount(page, 390);
  await page.evaluate(() => {
    card.remove();
    const now = Date.now(), iso = minutes => new Date(now + minutes * 60000).toISOString();
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries = [
      { id: 'next', name: 'Copenhagen - Vienna', legs: [{ id: 'next-leg', flight_number: 'OS992',
        departure: { utc_timestamp: iso(14400), timezone: 'Europe/Copenhagen' } }] },
      { id: 'arrived', name: 'Copenhagen - Cairo', legs: [{ id: 'arrived-leg', flight_number: 'MS760', origin_airport: 'CPH', destination_airport: 'CAI',
        departure: { utc_timestamp: iso(-313), timezone: 'Europe/Copenhagen' },
        arrival: { utc_timestamp: iso(-48), timezone: 'Africa/Cairo' },
        finished_at: iso(-14), evidence: { departure: iso(-291), touchdown: iso(-30), gate_arrival: iso(-14) } }] },
    ];
    // The deployed 0.3.9 sensor has saved leg evidence but no final_arrival_at.
    attrs.journeys = [
      { itinerary_id: 'arrived', leg_ids: ['arrived-leg'], departure_at: iso(-313), arrival_at: iso(-48),
        touchdown_at: iso(-30), completed: true, status: 'completed', completion_source: 'confirmed',
        tracking_required: true, api_stop_at: iso(90), expires_at: iso(1440) },
      { itinerary_id: 'next', leg_ids: ['next-leg'], departure_at: iso(14400), api_start_at: iso(14340), tracking_required: false },
    ];
    attrs.tracked_legs = [];
    attrs.tracking_source_health = 'no_flights';
    attrs.tracking_source_entity = 'sensor.fr24';
    attrs.tracking = { fetching: true, auto_track: true, tracking_required: true };
    hass.states['sensor.fr24'] = { state: '0', attributes: { flights: [] } };
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({ status_colors: { arrived: '#00ff00', landed: '#ff8800' } });
    document.body.append(schedule); schedule.hass = hass;
  });
  const select = page.locator('airport-itinerary-schedule #trip');
  await expect(select).toHaveValue('arrived');
  await expect(page.locator('.tracking-notice')).toHaveCount(0);
  await expect(page.locator('.badge')).toHaveText('Final arrival · at gate');
  await expect(page.locator('.endpoint-label').last()).toHaveText('Final arrival');
  await expect(page.locator('.endpoint-time').last()).toHaveCSS('color', 'rgb(0, 255, 0)');
  await page.locator('.flight-details > summary').click();
  await expect(page.getByText('Departure to gate', { exact: true }).locator('..').locator('strong')).toHaveText('4h 37m');
  await expect(page.getByText('Scheduled flight time', { exact: true }).locator('..').locator('strong')).toHaveText('4h 25m');
  await expect(page.getByText('Scheduled time elapsed', { exact: true })).toHaveCount(0);
  await page.screenshot({ path: testInfo.outputPath('retained-arrival.png') });
  // The gate/landing evidence also suppresses a number-only replacement watch.
  await page.evaluate(() => {
    schedule.shadowRoot.activeElement?.blur();
    hass.states['sensor.fr24'].attributes.flights = [{ flight_number: 'MS760', tracked_type: 'schedule' }];
    hass.states['sensor.flight_itineraries'].attributes.tracking_source_health = 'no_matching_flight';
    schedule.hass = { ...hass };
  });
  await expect(page.locator('.tracking-notice')).toHaveCount(0);
  // Reconciliation expiry, not the five-minute colour delay, advances selection.
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.journeys[0].api_stop_at = new Date(Date.now() - 1000).toISOString();
    schedule.hass = { ...hass };
  });
  await expect(select).toHaveValue('next');
  await expect(page.locator('.tracking-notice')).toContainText('Tracking starts');
  await select.selectOption('arrived');
  await expect(page.locator('.tracking-notice')).toHaveCount(0);
  await expect(page.locator('.badge')).toHaveText('Final arrival · at gate');
  // With only touchdown saved, disappearance must still say landed, not scheduled.
  await page.evaluate(() => {
    const leg = hass.states['sensor.flight_itineraries'].attributes.itineraries[1].legs[0];
    delete leg.evidence.gate_arrival;
    leg.finished_at = leg.evidence.touchdown;
    schedule.shadowRoot.activeElement?.blur(); schedule.hass = { ...hass }; schedule.render();
  });
  await expect(page.locator('.badge')).toHaveText('Landed · awaiting gate');
  await expect(page.locator('.tracking-notice')).toHaveCount(0);
  await expect(page.locator('.flight-details').getByText('Departure to landing', { exact: true }).locator('..').locator('strong')).toHaveText('4h 21m');
});


test('live ground flight changes to airborne and arrival from provider evidence', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    const now = Date.now();
    attrs.itineraries[0].legs = [{ id: 'leg', flight_number: 'MS760', departure: { utc_timestamp: new Date(now-3600000).toISOString(), timezone: 'UTC' }, arrival: { utc_timestamp: new Date(now+3600000).toISOString(), timezone: 'UTC' } }];
    attrs.tracked_legs = [{ itinerary_id: 'trip', leg_id: 'leg', is_live: true, on_ground: true, position_updated_at: new Date(now).toISOString() }];
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.setConfig({}); document.body.append(schedule); schedule.hass = hass;
  });
  await expect(page.locator('.badge')).toHaveText('On ground');
  await page.evaluate(() => { hass.states['sensor.flight_itineraries'].attributes.tracked_legs[0].on_ground = false; schedule.hass = { ...hass }; });
  await expect(page.locator('.badge')).toHaveText('Airborne');
  await page.evaluate(() => { Object.assign(hass.states['sensor.flight_itineraries'].attributes.tracked_legs[0], { on_ground: true, time_real_arrival: Date.now()/1000 }); schedule.hass = { ...hass }; });
  await expect(page.locator('.badge')).toHaveText('Landed · awaiting gate');
  await page.evaluate(() => { hass.states['sensor.flight_itineraries'].attributes.tracked_legs[0].gate_arrived_sent = true; schedule.hass = { ...hass }; });
  await expect(page.locator('.badge')).toHaveText('Final arrival · at gate');
});


test('airborne status survives clock skew and default progress colours follow status', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();
    const now=Date.now(),attrs=hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries[0].legs=[{id:'leg',flight_number:'MS760',departure:{utc_timestamp:new Date(now-3600000).toISOString(),timezone:'UTC'},arrival:{utc_timestamp:new Date(now+3600000).toISOString(),timezone:'UTC'}}];
    attrs.tracked_legs=[{itinerary_id:'trip',leg_id:'leg',is_live:true,on_ground:false,time_real_departure:(now-1800000)/1000,position_updated_at:new Date(now+15000).toISOString()}];
    window.schedule=document.createElement('airport-itinerary-schedule');
    schedule.style.setProperty('--info-color','#00bcd4');
    schedule.setConfig({});document.body.append(schedule);schedule.hass=hass;
  });
  const badge=page.locator('.badge'),departure=page.locator('.endpoint-time').first(),bar=page.locator('.progress-fill');
  await expect(badge).toHaveText('Airborne');
  await expect(badge).toHaveCSS('color','rgb(0, 188, 212)');
  await expect(departure).toHaveCSS('color','rgb(0, 188, 212)');
  await expect(bar).toHaveCSS('background-color','rgb(0, 188, 212)');
  const statuses=await page.evaluate(() => [750,0,15000,-1000].map(offset=>{
    hass.states['sensor.flight_itineraries'].attributes.tracked_legs[0].position_updated_at=new Date(Date.now()+offset).toISOString();
    schedule.hass={...hass};return schedule.shadowRoot.querySelector('.badge').textContent;
  }));
  expect(statuses).toEqual(['Airborne','Airborne','Airborne','Airborne']);
  await page.evaluate(() => schedule.setConfig({progress_color:'#ff00ff'}));
  await expect(badge).toHaveCSS('color','rgb(0, 188, 212)');
  await expect(departure).toHaveCSS('color','rgb(255, 0, 255)');
  await expect(bar).toHaveCSS('background-color','rgb(255, 0, 255)');
  await page.evaluate(() => schedule.setConfig({status_colors:{airborne:'#00ff00'}}));
  await expect(badge).toHaveCSS('color','rgb(0, 255, 0)');
  await expect(departure).toHaveCSS('color','rgb(0, 255, 0)');
  await expect(bar).toHaveCSS('background-color','rgb(0, 255, 0)');
  await page.evaluate(() => {hass.states['sensor.flight_itineraries'].attributes.tracked_legs[0].position_updated_at=new Date(Date.now()-301000).toISOString();schedule.hass={...hass};});
  await expect(badge).toHaveText('In transit');
});


test('only four flight elements are coloured and explicit colours work without FR24', async ({ page }) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();const now=Date.now(),attrs=hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries[0].legs=[{id:'leg',flight_number:'MS760',origin_airport:'CPH',destination_airport:'CAI',departure:{utc_timestamp:new Date(now-3600000).toISOString(),timezone:'UTC'},arrival:{utc_timestamp:new Date(now+3600000).toISOString(),timezone:'UTC'}}];
    window.liveRow={itinerary_id:'trip',leg_id:'leg',is_live:true,on_ground:false,position_updated_at:new Date(now).toISOString(),time_real_departure:(now-1800000)/1000};attrs.tracked_legs=[liveRow];
    window.schedule=document.createElement('airport-itinerary-schedule');schedule.style.setProperty('--info-color','#00bcd4');schedule.style.setProperty('--disabled-text-color','#888888');
    schedule.setConfig({});document.body.append(schedule);schedule.hass=hass;
  });
  const departure=page.locator('.endpoint-time').first(),arrival=page.locator('.endpoint-time').last(),badge=page.locator('.badge'),bar=page.locator('.progress-fill');
  for(const target of [departure,badge]) await expect(target).toHaveCSS('color','rgb(0, 188, 212)');
  await expect(arrival).toHaveCSS('color','rgb(255, 255, 255)');
  await expect(bar).toHaveCSS('background-color','rgb(0, 188, 212)');
  const plainSelector='.flight-heading h3,.flight-label,.endpoint-code,.endpoint-label,.airport-date,.route-arrow,.schedule-note,.flight-details summary,.flight-details strong,.leg-collapse,.remove-flight';
  const plain=await page.locator(plainSelector).evaluateAll(elements=>elements.map(el=>getComputedStyle(el).color));
  await page.locator('airport-itinerary-schedule').screenshot({path:'test-results/airborne-colours-490.png'});
  await page.evaluate(() => {hass.states['sensor.flight_itineraries'].attributes.tracked_legs=[];schedule.hass={...hass};});
  await expect(departure).toHaveCSS('color','rgb(255, 152, 0)');
  await expect(arrival).toHaveCSS('color','rgb(255, 255, 255)');
  await expect(bar).toHaveCSS('background-color','rgb(136, 136, 136)');
  await page.evaluate(() => schedule.setConfig({status_colors:{scheduled:'#00ff00'}}));
  for(const target of [departure,badge]) await expect(target).toHaveCSS('color','rgb(0, 255, 0)');
  await expect(arrival).toHaveCSS('color','rgb(255, 255, 255)');
  await expect(bar).toHaveCSS('background-color','rgb(0, 255, 0)');
  await page.evaluate(() => schedule.setConfig({status_colors:{scheduled:'#00ff00'},progress_color:'#ff00ff'}));
  await expect(badge).toHaveCSS('color','rgb(0, 255, 0)');
  await expect(departure).toHaveCSS('color','rgb(255, 0, 255)');
  await expect(arrival).toHaveCSS('color','rgb(255, 255, 255)');
  await expect(bar).toHaveCSS('background-color','rgb(255, 0, 255)');
  await page.evaluate(() => {hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs[0].arrival.utc_timestamp=new Date(Date.now()-600000).toISOString();schedule.hass={...hass};});
  await expect(badge).toHaveText('Finished (scheduled)');
  await expect(bar).toHaveCSS('background-color','rgb(255, 0, 255)');
  await expect(departure).toHaveCSS('color','rgb(255, 0, 255)');
  await page.evaluate(() => schedule.setConfig({status_colors:{scheduled:'#00ff00'},progress_color:'#ff00ff',finished_color:'#aabbcc'}));
  for(const target of [departure,badge]) await expect(target).toHaveCSS('color','rgb(170, 187, 204)');
  await expect(arrival).toHaveCSS('color','rgb(255, 255, 255)');
  await expect(bar).toHaveCSS('background-color','rgb(170, 187, 204)');
  // Detail fields can disappear with live data; compare the persistent visual elements.
  const remaining=await page.locator(plainSelector).evaluateAll(elements=>elements.map(el=>getComputedStyle(el).color));
  expect(remaining.every(color=>color==='rgb(255, 255, 255)' || color==='rgb(221, 221, 221)' || color==='rgb(198, 40, 40)')).toBeTruthy();
  expect(remaining.slice(0,8)).toEqual(plain.slice(0,8));
});

test('arrival colour requires landing evidence and survives tracked-record cleanup', async ({ page }, testInfo) => {
  await mount(page);
  await page.evaluate(() => {
    card.remove();
    const now = Date.now(), attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries[0].legs = [{ id: 'leg', flight_number: 'MS760',
      departure: { utc_timestamp: new Date(now - 3600000).toISOString(), timezone: 'UTC' },
      arrival: { utc_timestamp: new Date(now + 3600000).toISOString(), timezone: 'UTC' } }];
    attrs.tracked_legs = [{ itinerary_id: 'trip', leg_id: 'leg', is_live: true,
      on_ground: true, position_updated_at: new Date(now).toISOString(),
      time_estimated_arrival: (now + 1800000) / 1000 }];
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.style.setProperty('--success-color', '#00ff00');
    schedule.setConfig({ progress_color: '#ff00ff' });
    document.body.append(schedule); schedule.hass = hass;
  });
  const arrival = page.locator('.endpoint-time').last();
  await expect(page.locator('.badge')).toHaveText('On ground');
  await expect(page.locator('.endpoint-label').last()).toHaveText('Estimated arrival');
  await expect(arrival).toHaveCSS('color', 'rgb(255, 255, 255)');
  await page.evaluate(() => {
    const row = hass.states['sensor.flight_itineraries'].attributes.tracked_legs[0];
    row.on_ground = false;
    row.time_estimated_arrival = (Date.now() - 600000) / 1000;
    schedule.hass = { ...hass };
  });
  await expect(page.locator('.badge')).toHaveText('Airborne');
  await expect(arrival).toHaveCSS('color', 'rgb(255, 255, 255)');
  for (const evidence of ['time_real_landing', 'time_real_arrival', 'time_gate_arrival', 'landing', 'gate_arrival']) {
    await page.evaluate(field => {
      const attrs = hass.states['sensor.flight_itineraries'].attributes;
      attrs.tracked_legs = [{ itinerary_id: 'trip', leg_id: 'leg', is_live: true,
        on_ground: true, position_updated_at: new Date().toISOString(), [field]: Date.now() / 1000 }];
      schedule.hass = { ...hass };
    }, evidence);
    const atGate = ['time_gate_arrival', 'gate_arrival'].includes(evidence);
    await expect(arrival).toHaveCSS('color', atGate ? 'rgb(0, 255, 0)' : 'rgb(255, 0, 255)');
  }
  await page.evaluate(() => schedule.setConfig({}));
  await expect(arrival).toHaveCSS('color', 'rgb(0, 255, 0)');
  await page.evaluate(() => {
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries[0].legs[0].finished_at = new Date(Date.now() - 600000).toISOString();
    attrs.itineraries[0].legs[0].evidence = { gate_arrival: attrs.itineraries[0].legs[0].finished_at };
    attrs.tracked_legs = [];
    schedule.setConfig({}); schedule.hass = { ...hass };
  });
  // The default finish timer must not grey the times while the status stays green.
  const departure = page.locator('.endpoint-time').first();
  const badge = page.locator('.badge'), bar = page.locator('.progress-fill');
  for (const config of [{}, { progress_color: '#ff00ff' }, { status_colors: { arrived: '#00ff00' }, progress_color: '#ff00ff' }]) {
    await page.evaluate(config => schedule.setConfig(config), config);
    await expect(badge).toHaveCSS('color', 'rgb(0, 255, 0)');
    await expect(departure).toHaveCSS('color', 'rgb(0, 255, 0)');
    await expect(arrival).toHaveCSS('color', 'rgb(0, 255, 0)');
    await expect(bar).toHaveCSS('background-color', 'rgb(0, 255, 0)');
  }
  await page.screenshot({ path: testInfo.outputPath('gate-colours.png') });
  await page.evaluate(() => schedule.setConfig({ finished_color: '#aabbcc' }));
  await expect(badge).toHaveCSS('color', 'rgb(170, 187, 204)');
  await expect(departure).toHaveCSS('color', 'rgb(170, 187, 204)');
  await expect(arrival).toHaveCSS('color', 'rgb(170, 187, 204)');
  await expect(bar).toHaveCSS('background-color', 'rgb(170, 187, 204)');
  await page.evaluate(() => {
    const leg = hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs[0];
    delete leg.finished_at;
    leg.completed = true;
    leg.evidence = { manual_completion: new Date().toISOString() };
    schedule.setConfig({ status_colors: { completed: '#00ff00' }, progress_color: '#ff00ff' });
    schedule.hass = { ...hass };
  });
  await expect(arrival).toHaveCSS('color', 'rgb(255, 255, 255)');
});

for (const width of [320, 390, 490]) {
  test(`landing and gate colours survive cleanup at width ${width}`, async ({ page }, testInfo) => {
    await mount(page);
    await page.evaluate(width => {
      card.remove();
      const now = Date.now(), attrs = hass.states['sensor.flight_itineraries'].attributes;
      attrs.itineraries[0].legs = [{ id: 'leg', flight_number: 'MS760', origin_airport: 'CPH', destination_airport: 'CAI',
        departure: { utc_timestamp: new Date(now - 14400000).toISOString(), timezone: 'Europe/Copenhagen' },
        arrival: { utc_timestamp: new Date(now - 1800000).toISOString(), timezone: 'Africa/Cairo' },
        finished_at: new Date(now - 1200000).toISOString(),
        evidence: { touchdown: new Date(now - 1200000).toISOString() } }];
      attrs.tracked_legs = [{ itinerary_id: 'trip', leg_id: 'leg', is_live: true, on_ground: true,
        has_landed: true, gate_arrived_sent: false, ground_speed: 12, position_updated_at: new Date(now).toISOString() }];
      window.schedule = document.createElement('airport-itinerary-schedule');
      schedule.style.width = `${width}px`;
      schedule.style.display = 'block';
      schedule.setConfig({ status_colors: { landed: '#ff8800', arrived: '#00ff00' }, finished_color: '#aabbcc',
        finish_delay_seconds: 300, auto_collapse_after_minutes: 1 });
      document.body.append(schedule); schedule.hass = hass;
    }, width);
    const badge = page.locator('.badge'), arrival = page.locator('.endpoint-time').last();
    await expect(badge).toHaveText('Taxiing to gate');
    await expect(arrival).toHaveCSS('color', 'rgb(255, 136, 0)');
    await expect(page.locator('.leg-body')).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`taxiing-${width}.png`) });
    await page.evaluate(() => { hass.states['sensor.flight_itineraries'].attributes.tracked_legs = []; schedule.hass = { ...hass }; });
    await expect(badge).toHaveText('Landed · awaiting gate');
    await expect(arrival).toHaveCSS('color', 'rgb(255, 136, 0)');
    await expect(page.locator('.progress-fill')).toHaveCSS('background-color', 'rgb(255, 136, 0)');
    await page.evaluate(() => {
      hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs[0].evidence.gate_arrival = new Date().toISOString();
      schedule.hass = { ...hass };
    });
    await expect(badge).toHaveText('Final arrival · at gate');
    await expect(badge).toHaveCSS('color', 'rgb(0, 255, 0)');
    await expect(arrival).toHaveCSS('color', 'rgb(0, 255, 0)');
    await expect(page.locator('.leg-body')).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`at-gate-${width}.png`) });
    expect(await page.locator('airport-itinerary-schedule').evaluate(el => el.shadowRoot.querySelector('.card').scrollWidth <= el.clientWidth)).toBeTruthy();
    await page.evaluate(() => {
      hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs[0].evidence.gate_arrival = new Date(Date.now() - 301000).toISOString();
      schedule.hass = { ...hass };
    });
    await expect(arrival).toHaveCSS('color', 'rgb(170, 187, 204)');
    await expect(page.locator('.leg-body')).toBeVisible();
    await page.evaluate(() => {
      hass.states['sensor.flight_itineraries'].attributes.itineraries[0].legs[0].evidence.gate_arrival = new Date(Date.now() - 361000).toISOString();
      schedule.hass = { ...hass };
    });
    await expect(page.locator('.leg-body')).toBeHidden();
  });
}


test('yesterday arrival keeps actual times and colours with fetching off', async ({ page }, testInfo) => {
  await page.clock.install({ time: new Date('2026-11-01T08:00:00Z') });
  await mount(page, 390);
  await page.evaluate(() => {
    card.remove();
    const attrs = hass.states['sensor.flight_itineraries'].attributes;
    attrs.itineraries = [{ id: 'trip', name: 'Copenhagen - Cairo', legs: [{ id: 'leg', flight_number: 'MS760',
      origin_airport: 'CPH', destination_airport: 'CAI',
      departure: { utc_timestamp: '2026-10-31T14:05:00Z', timezone: 'Europe/Copenhagen' },
      arrival: { utc_timestamp: '2026-10-31T18:30:00Z', timezone: 'Africa/Cairo' },
      evidence: { departure: '2026-10-31T14:27:00Z', touchdown: '2026-10-31T18:48:57Z', gate_arrival: '2026-10-31T19:04:58Z' },
      finished_at: '2026-10-31T19:04:58Z', arrival_phase: 'at_gate', final_arrival_at: '2026-10-31T19:04:58Z' }] }];
    attrs.tracked_legs = [];
    attrs.tracking_source_health = 'no_flights';
    attrs.tracking = { fetching: false, tracking_required: false, fetching_reason: 'off' };
    window.schedule = document.createElement('airport-itinerary-schedule');
    schedule.style.setProperty('--success-color', '#4caf50');
    schedule.setConfig({}); document.body.append(schedule); schedule.hass = hass;
  });
  await expect(page.locator('.tracking-notice')).toHaveCount(0);
  await expect(page.locator('.badge')).toHaveText('Final arrival · at gate');
  await expect(page.locator('.endpoint-time').first()).toHaveText('15:27');
  await expect(page.locator('.endpoint-time').last()).toHaveText('21:04');
  await expect(page.locator('.schedule-note')).toHaveText('Gate arrival confirmed by FR24.');
  await page.locator('.itinerary-details > summary').click();
  await expect(page.locator('.trip-metric strong')).toHaveText(['4h 37m', '4h 25m', 'Final arrival · at gate']);
  await expect(page.locator('.trip-summary-note')).toContainText('retained from tracking');
  const colour = await page.locator('.badge').evaluate(el => getComputedStyle(el).color);
  await expect(page.locator('.endpoint-time').first()).toHaveCSS('color', colour);
  await expect(page.locator('.endpoint-time').last()).toHaveCSS('color', colour);
  await expect(page.locator('.progress-fill')).toHaveCSS('background-color', colour);
  await page.screenshot({ path: testInfo.outputPath('yesterday-arrival.png') });
  await page.evaluate(() => schedule.shadowRoot.activeElement?.blur());
  await page.clock.fastForward(86400000);
  await expect(page.locator('.badge')).toHaveText('Final arrival · at gate');
  await expect(page.locator('.trip-metric strong')).toHaveText(['4h 37m', '4h 25m', 'Final arrival · at gate']);
  await page.evaluate(() => {
    hass.states['sensor.flight_itineraries'].attributes.tracking_source_health = 'disabled';
    hass.states['sensor.flight_itineraries'].attributes.tracking.connection_enabled = false;
    schedule.hass = { ...hass };
  });
  await expect(page.locator('.tracking-notice')).toHaveCount(0);
  await expect(page.locator('.badge')).toHaveText('Final arrival · at gate');
});
