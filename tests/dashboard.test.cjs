// Presentation regressions execute the real page script with synthetic TEST- data.
// JSDOM checks DOM behavior, not browser layout or visual accessibility.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM, VirtualConsole } = require('jsdom');

const template = fs.readFileSync('dashboard/index.html', 'utf8');

test('sites and commodity/type keys are visible by default, including contextual sites', async t => {
  const data = fixture();
  data.sites[0] = { ...data.sites[0], type: 'mine_unspecified', latitude: 38.5,
    longitude: 30.5, coordinate_precision: 'facility_approximate' };
  data.sites[1] = { ...data.sites[1], type: 'archaeological_quarry', latitude: 38.5,
    longitude: 32.5, coordinate_precision: 'facility_approximate' };
  const page = boot(t, { data });
  assert.equal(page.document.querySelector('[data-layer="both"]').getAttribute('aria-pressed'), 'true');
  assert.equal(page.document.querySelectorAll('#map [data-sitekey]').length, 2);
  assert.match(page.document.getElementById('maplegend').textContent, /coal and lignite/);
  page.change('f-site-type', 'archaeological_quarry');
  assert.equal(page.document.querySelectorAll('#map [data-sitekey]').length, 1);
  const output = JSON.parse(await page.download('dl-json'));
  assert.equal(output.sites.length, 1);
  assert.equal(output.incidents.length, 2, 'site type must not remove incident records');
  assert.equal(new URL(page.window.location.href).searchParams.get('siteType'), 'archaeological_quarry');
});

test('coarse sites are grouped, unknown sites remain listed, and sites-only has no death legend', t => {
  const data = fixture();
  data.sites[1].province_code = '';
  const page = boot(t, { data });
  assert.equal(page.document.querySelectorAll('#map .site-group').length, 1);
  assert.match(page.document.getElementById('site-coverage').textContent,
    /0 with facility-level coordinates, 1 grouped by province, 1 without a usable map location/);
  page.document.querySelector('[data-layer="sites"]').click();
  assert.equal(page.document.querySelectorAll('#map .research-circle').length, 0);
  assert.doesNotMatch(page.document.getElementById('maplegend').textContent, /people lost:/);
  assert.match(page.document.querySelector('#sites-table tbody').textContent, /TEST saha B/);
});

test('timeline exposes small incidents and policies by year and can focus the map', t => {
  const data = fixture();
  data.policy_events = [{ date: '2099-06-01', kind: 'law', label_en: 'TEST policy',
    label_tr: 'TEST politika', source_url: 'https://example.test/TEST-policy' }];
  const page = boot(t, { data });
  page.document.querySelector('[data-year="2099"]').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
  const detail = page.document.getElementById('year-detail');
  assert.match(detail.textContent, /TEST olay B/);
  assert.match(detail.textContent, /TEST policy/);
  detail.querySelector('[data-year-record]').click();
  assert.equal(page.document.getElementById('detail').hidden, false);
  page.document.getElementById('detail-close').click();
  // The DOM harness does not implement scrolling; navigation remains optional.
  page.document.getElementById('timeline-focus-map').click();
  assert.equal(page.document.getElementById('f-from').value, '2099');
  assert.equal(page.document.getElementById('f-to').value, '2099');
  assert.equal(page.document.querySelectorAll('#records tbody tr').length, 1);
  assert.equal(page.document.querySelectorAll('#chart .year-hit').length, 2,
    'timeline keeps the full chronology after a map filter');
});

test('timeline keeps uncertain tolls visible and switches language with its selection', t => {
  const data = fixture();
  data.incidents[1].casualty_status = 'disputed';
  const page = boot(t, { data });
  assert.match(page.document.getElementById('timeline-events').textContent, /disputed/i);
  page.document.querySelector('[data-year="2099"]').dispatchEvent(new page.window.MouseEvent('click', { bubbles: true }));
  page.document.querySelector('[data-lang="tr"]').click();
  assert.match(page.document.getElementById('year-detail').textContent, /2099/);
  assert.match(page.document.getElementById('timeline-events').textContent, /tartışmalı/i);
  assert.equal(page.document.querySelector('#sector-chart').closest('details').open, false);
});
function fixture() {
  const incidents = ['A', 'B'].map((id, n) => ({
    public_incident_id: `TEST-${id}`, canonical_title_tr: `TEST olay ${id}`,
    incident_start_datetime: `${2098 + n}-05-10`, date_precision: 'exact_date',
    province_code: `TEST-${id}`, fatalities_current: n + 1,
    casualty_status: 'final', latitude: null, longitude: null,
  }));
  return {
    incidents, sites: ['A', 'B'].map(id => ({
      ref: `TEST-site-${id}`, name: `TEST saha ${id}`, type: 'mine',
      commodity_code: id === 'A' ? 'coal' : 'gold', status: 'unknown',
      province_code: `TEST-${id}`, organizations: [{ name: 'TEST A & B', role: 'operator' }],
      source_url: 'https://example.test/TEST-source', latitude: null, longitude: null,
    })),
    citations: Object.fromEntries(incidents.map(i => [i.public_incident_id, [{
      organization: 'TEST source', title: 'TEST evidence', url: 'https://example.test/TEST-source',
    }]])),
    classifications: Object.fromEntries(incidents.map(i => [i.public_incident_id, [{
      system: 'project_event_mechanism', code: 'TEST-collapse',
      label_en: 'TEST collapse', label_tr: 'TEST göçük', assertion_status: 'reported',
    }]])),
    province_names: { 'TEST-A': 'TEST ili A', 'TEST-B': 'TEST ili B' },
    province_centroids: {}, provinces_geo: [
      { code: 'TEST-A', rings: [[[38, 30], [38, 31], [39, 31], [39, 30], [38, 30]]] },
      { code: 'TEST-B', rings: [[[38, 32], [38, 33], [39, 33], [39, 32], [38, 32]]] },
    ],
    aggregates: [], policy_events: [], coverage_gap: { years: [], total_gap: 0 },
    rate_context: [], pipeline: { records_in_review: 0, source_documents: 2,
      claims_total: 6, decisions_total: 6 },
    export_timestamp: '2099-06-01T00:00:00Z', schema_version: 'TEST-1',
  };
}
function boot(t, { data = fixture(), storageBlocked = false, query = '' } = {}) {
  const errors = [], blobs = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', error => errors.push(error.message));
  const dom = new JSDOM(template, {
    url: `https://example.test/${query}`, runScripts: 'dangerously',
    virtualConsole: vc,
    beforeParse(window) {
      window.MINING_DATA = data;
      window.matchMedia = query => ({ matches: query.includes('reduced-motion') });
      window.URL.createObjectURL = blob => { blobs.push(blob); return 'blob:TEST'; };
      window.URL.revokeObjectURL = () => {};
      window.HTMLAnchorElement.prototype.click = () => {};
      // Use Node's Blob so downloads can be decoded without a browser's FileReader.
      window.Blob = Blob;
      if (storageBlocked) Object.defineProperty(window, 'localStorage', {
        get() { throw new window.DOMException('TEST denied', 'SecurityError'); },
      });
    },
  });
  t.after(() => dom.window.close());
  assert.deepEqual(errors, [], 'page must boot without JavaScript errors');
  t.after(() => assert.deepEqual(errors, [], 'interactions must not throw'));
  const document = dom.window.document;
  return { window: dom.window, document, data,
    change(id, value) {
      document.getElementById(id).value = value;
      document.getElementById(id).dispatchEvent(new dom.window.Event('change'));
    },
    async download(id) {
      document.getElementById(id).click();
      assert.ok(blobs.length, 'click must create a download');
      return blobs.pop().text();
    },
  };
}

test('JSON downloads honor filters and keep only matching evidence', async t => {
  const page = boot(t);
  page.change('f-province', 'TEST-A');
  const json = JSON.parse(await page.download('dl-json'));
  assert.deepEqual(json.incidents.map(i => i.public_incident_id), ['TEST-A']);
  assert.deepEqual(json.sites.map(s => s.ref), ['TEST-site-A']);
  assert.deepEqual(Object.keys(json.citations), ['TEST-A']);
  assert.deepEqual(Object.keys(json.classifications), ['TEST-A']);
  assert.equal(json.filters.province, 'TEST-A');
  assert.equal(json.context.scope, 'full_register_and_sector');
  page.document.getElementById('f-clear').click();
  assert.equal(JSON.parse(await page.download('dl-json')).incidents.length, 2);
});

test('year changes survive a shared URL and reload', t => {
  const page = boot(t);
  page.change('f-from', '2099');
  assert.equal(new URL(page.window.location.href).searchParams.get('from'), '2099');
  const restored = boot(t, { query: page.window.location.search });
  assert.equal(restored.document.querySelectorAll('#records .rec-row').length, 1);
  assert.equal(restored.document.querySelector('#records .rec-row').dataset.id, 'TEST-B');
  restored.change('f-to', '2098');
  assert.equal(new URL(restored.window.location.href).searchParams.get('to'), '2098');
  assert.equal(restored.document.querySelector('#records .rec-row').dataset.id, 'TEST-A');
});

test('blocked storage still permits startup and language switching', t => {
  const page = boot(t, { storageBlocked: true });
  page.document.querySelector('[data-lang="tr"]').click();
  assert.equal(page.document.documentElement.lang, 'tr');
  assert.equal(page.document.querySelectorAll('#records .rec-row').length, 2);
  assert.ok(page.document.querySelector('#map svg'));
});

test('source text renders literally and unsafe links do not become anchors', t => {
  const data = fixture();
  const hostile = 'TEST <img src=x onerror="window.TEST_ATTACK=1"> & "quote"';
  data.incidents[0].canonical_title_tr = hostile;
  data.sites[0].name = hostile;
  data.sites[0].commodity_label = hostile;
  data.sites[0].source_url = 'javascript:window.TEST_ATTACK=1';
  data.classifications['TEST-A'][0].label_en = hostile;
  data.classifications['TEST-A'][0].label_tr = hostile;
  data.citations['TEST-A'][0] = { organization: hostile, title: hostile,
    url: 'javascript:window.TEST_ATTACK=1' };
  const page = boot(t, { data });
  page.document.querySelector('#records .rec-row').click();
  assert.equal(page.document.querySelector('#detail-body h3').textContent, hostile);
  assert.equal(page.document.querySelectorAll('img, a[href^="javascript:"]').length, 0);
  assert.equal(page.window.TEST_ATTACK, undefined);
  assert.ok(page.document.querySelector('#mechanisms').textContent.includes(hostile));
});

test('CSV preserves raw text and numbers, quotes CRs, and neutralizes formulas', async t => {
  const data = fixture();
  data.incidents[0].canonical_title_tr = '=TEST("İşçi")';
  data.incidents[1].canonical_title_tr = 'TEST A\rB';
  data.incidents[0].longitude = -1;
  const page = boot(t, { data });
  const csv = await page.download('dl-records');
  assert.ok(csv.includes('"\'=TEST(""İşçi"")"'));
  assert.ok(csv.includes('"TEST A\rB"'));
  assert.ok(csv.includes(',-1,'), 'negative numeric coordinates must remain numbers');
  const sites = await page.download('dl-sites');
  assert.ok(sites.includes('TEST A & B (operator)'));
  assert.ok(!sites.includes('&amp;'));
  const json = JSON.parse(await page.download('dl-json'));
  assert.equal(json.incidents[0].canonical_title_tr, '=TEST("İşçi")');
});

test('empty selections retain CSV schemas and JSON contains no unrelated evidence', async t => {
  const page = boot(t, { query: '?province=TEST-A&from=2099&commodity=gold' });
  const csv = await page.download('dl-records');
  assert.equal(csv.trim().split('\n').length, 1);
  assert.equal(csv.trim().split(',').length, 14);
  assert.equal((await page.download('dl-sites')).trim().split(',').length, 12);
  const json = JSON.parse(await page.download('dl-json'));
  assert.deepEqual(json.incidents, []);
  assert.deepEqual(json.sites, []);
  assert.deepEqual(json.citations, {});
});

test('an empty public export has finite, disabled year filters', t => {
  const data = fixture();
  data.incidents = []; data.sites = []; data.citations = {}; data.classifications = {};
  const page = boot(t, { data });
  assert.equal(page.document.getElementById('f-from').disabled, true);
  assert.ok(Number.isFinite(+page.document.getElementById('f-from').value));
  assert.equal(page.document.querySelectorAll('#records .rec-row').length, 0);
});
