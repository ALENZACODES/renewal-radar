import {test} from 'node:test';
import assert from 'node:assert/strict';
import {RateRefreshController, rateTrackingView} from '../frontend/js/rate-tracker.js';
import {answerLocalMortgageQuestion} from '../frontend/js/helper-answers.js';

test('concurrent refresh commands share one in-flight request', async () => {
  let calls = 0;
  let resolve;
  const fetchSnapshot = () => {calls++; return new Promise(done => {resolve = done;});};
  const controller = new RateRefreshController({fetchSnapshot, forceRefresh: fetchSnapshot, onUpdate() {}});
  const first = controller.refresh();
  const second = controller.refresh();
  assert.equal(first, second);
  await Promise.resolve();
  assert.equal(calls, 1);
  resolve({revision: 1});
  assert.equal((await first).revision, 1);
});

test('manual refresh uses the force endpoint and reports source results', async () => {
  let forced = 0;
  let update;
  const controller = new RateRefreshController({fetchSnapshot: async () => ({}), forceRefresh: async () => {forced++; return {data_status: 'unavailable'};}, onUpdate: value => {update = value;}});
  await controller.refresh(true);
  assert.equal(forced, 1);
  assert.equal(update.data_status, 'unavailable');
});

test('network failure is surfaced and the controller can retry', async () => {
  let fail = true;
  let error;
  const controller = new RateRefreshController({fetchSnapshot: async () => {if (fail) throw new Error('Offline'); return {revision: 2};}, onUpdate() {}, onError: value => {error = value;}});
  assert.equal(await controller.refresh(), null);
  assert.equal(error.message, 'Offline');
  fail = false;
  assert.equal((await controller.refresh()).revision, 2);
});

test('hidden tabs skip scheduled refreshes and stop removes the timer', async () => {
  let timer;
  let cancelled;
  let calls = 0;
  const documentObject = {visibilityState: 'hidden', addEventListener() {}, removeEventListener() {}};
  const controller = new RateRefreshController({fetchSnapshot: async () => {calls++; return {};}, onUpdate() {}, documentObject,
    schedule: callback => {timer = callback; return 7;}, cancel: id => {cancelled = id;}});
  controller.start();
  await controller.pending;
  assert.equal(calls, 1);
  await timer();
  assert.equal(calls, 1);
  controller.stop();
  assert.equal(cancelled, 7);
});

test('tracking output labels cached data and escapes imported observations', () => {
  const html = rateTrackingView({data_status: 'cached-stale', checked_at: '2026-10-14', changes: [{label: '<script>', previous: 5, current: 4.75, change_basis_points: -25, observed_at: '2026-10-13'}]});
  assert.match(html, /Cached observations/);
  assert.match(html, /-25 bps/);
  assert.ok(!html.includes('<script>'));
});

test('default timers preserve the browser global receiver', async () => {
  const originalSet = globalThis.setTimeout;
  const originalClear = globalThis.clearTimeout;
  let cancelled = false;
  globalThis.setTimeout = function() {assert.equal(this, globalThis); return 8;};
  globalThis.clearTimeout = function(id) {assert.equal(this, globalThis); assert.equal(id, 8); cancelled = true;};
  try {
    const controller = new RateRefreshController({fetchSnapshot: async () => ({}), onUpdate() {}});
    controller.start();
    await controller.pending;
    controller.stop();
    assert.equal(cancelled, true);
  } finally {
    globalThis.setTimeout = originalSet;
    globalThis.clearTimeout = originalClear;
  }
});

test('local helper labels official cached observations instead of claiming live rates', () => {
  const answer = answerLocalMortgageQuestion('Show the current prime rate', {market: {
    data_status: 'cached-stale', checked_at: '2026-10-14T12:00:00Z',
    series: {prime: {value: 4.75, label: 'Typical bank prime', observed_at: '2026-10-13', source_url: 'https://www.bankofcanada.ca/valet/observations/V80691311/json'}},
  }});
  assert.equal(answer.intent, 'market');
  assert.match(answer.claims[0].text, /Cached observation/);
  assert.match(answer.claims[0].text, /Published 2026-10-13/);
  assert.equal(answer.evidence[0].source, 'official-market');
});
