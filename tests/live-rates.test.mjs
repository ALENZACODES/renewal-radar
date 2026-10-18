import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {liveRatesView, ageText} from '../frontend/js/live-rates.js';

const row = (over) => ({id: 'P021', name: 'RBC', type: 'bank', tier: 'primary', tier_label: 'Live', as_of: '2026-10-15T03:00:00+00:00',
  source_url: 'https://www.rbcroyalbank.com/mortgages/mortgage-rates.html', lender_specific: true,
  rates: {'12': {posted: 5.74, special: 5.14}, '36': {posted: 6.25, special: 4.99}, '60': {posted: 6.19, special: 5.14}},
  five_year: {posted: 6.19, special: 5.14, advertised: 5.14}, tried: [{tier: 'primary', ok: true, reason: 'ok'}], ...over});

const board = {refreshed_at: '2026-10-15T03:00:00+00:00', anchor: {boc_5y_posted: 6.19, goc_5y: 3.55, boc_5y_posted_date: '2026-10-14'},
  banks: [row(), row({id: 'P027', name: 'BMO', tier: 'boc_typical', tier_label: 'Bank of Canada big-six typical', lender_specific: false,
    tried: [{tier: 'primary', ok: false, reason: 'ReadTimeout'}]})],
  credit_unions: [row({id: 'CU01', name: 'Meridian', type: 'credit_union', five_year: {posted: 6.49, special: 4.74, advertised: 4.74}}),
    row({id: 'CU04', name: 'Servus', type: 'credit_union', tier: 'unavailable', tier_label: 'Unavailable', lender_specific: false,
      rates: {}, five_year: {}, source_url: null})]};

test('banks show posted and special, credit unions show advertised', () => {
  const html = liveRatesView({liveRates: board});
  assert.match(html, /6\.19%/);
  assert.match(html, /5\.14%/);
  assert.match(html, /4\.74%/);
  assert.match(html, /5-yr advertised/);
});

test('non-lender-specific and unavailable rows are clearly marked', () => {
  const html = liveRatesView({liveRates: board});
  assert.match(html, /Bank of Canada big-six typical \*/);
  assert.match(html, /Unavailable/);
});

test('each attempt is visible on hover', () => {
  assert.match(liveRatesView({liveRates: board}), /title="primary: ReadTimeout"/);
});

test('age text', () => {
  const now = new Date('2026-10-15T05:00:00Z');
  assert.equal(ageText('2026-10-15T04:30:00+00:00', now), '30 min ago');
  assert.equal(ageText('2026-10-15T01:00:00+00:00', now), '4 h ago');
  assert.equal(ageText('wayback 20261014', now), 'wayback 20261014');
});

test('loading and error states', () => {
  assert.match(liveRatesView({}), /Loading current rates/);
  assert.match(liveRatesView({liveRatesError: 'offline'}), /offline/);
});

test('page is registered, cached offline and wired to the API', () => {
  const html = readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  const sw = readFileSync(new URL('../frontend/service-worker.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../frontend/js/app.js', import.meta.url), 'utf8');
  assert.match(html, /data-nav="live"/);
  assert.match(sw, /\/js\/live-rates\.js/);
  assert.match(sw, /\/js\/lender-exact\.js/);
  assert.match(app, /live-rates-refresh/);
});


test('private and B lenders get their own section with a no-public-rates note', () => {
  const alt = {...board, alternative_lenders: [row({id: 'ALT08', name: 'Peoples Group', type: 'alternative',
    five_year: {posted: 5.99, special: null, advertised: 5.99}})]};
  const html = liveRatesView({liveRates: alt});
  assert.match(html, /Private and B lenders/);
  assert.match(html, /Peoples Group/);
  assert.match(html, /publish no public rates/);
});
