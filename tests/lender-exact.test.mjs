import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {lenderExactRequest, lenderExactView, lenderExactDefaults, LENDERS} from '../frontend/js/lender-exact.js';

test('request omits blank optional fields instead of sending zero', () => {
  const body = lenderExactRequest({...lenderExactDefaults(), discount: '', maturity: '', payout: ''});
  assert.equal('discount' in body, false);
  assert.equal('maturity' in body, false);
  assert.equal('payout' in body, false);
  assert.equal(body.amort_months, 300);
});

test('request carries amortization, maturity and payout when supplied', () => {
  const body = lenderExactRequest({...lenderExactDefaults(), amort_months: '240', payout: '2026-10-14'});
  assert.equal(body.amort_months, 240);
  assert.equal(body.maturity, '2028-10-15');
  assert.equal(body.payout, '2026-10-14');
  assert.equal(body.lender, 'TD');
});

test('client name never goes into the penalty request', () => {
  const body = lenderExactRequest({...lenderExactDefaults(), client_name: 'Private Person'});
  assert.equal(JSON.stringify(body).includes('Private Person'), false);
});

test('exact vs estimate labels follow the server status', () => {
  const base = {lenderExact: lenderExactDefaults()};
  const r = {penalty: 12832, three_month: 4890, ird: 12832, remaining_months: 24.06, compare_term: 24,
             compare_posted: 5.29, discount: 2, method: 'IRD', rates_source: 'supplied'};
  assert.match(lenderExactView({...base, lenderExactResult: {...r, status: 'exact-method'}}), /EXACT LENDER METHOD/);
  assert.match(lenderExactView({...base, lenderExactResult: {...r, status: 'estimate'}}), /ESTIMATE/);
});

test('matured term shows no charge', () => {
  const html = lenderExactView({lenderExact: lenderExactDefaults(),
    lenderExactResult: {method: 'matured', penalty: 0, status: 'exact-method', rates_source: 'supplied'}});
  assert.match(html, /Matured: no prepayment charge/);
});

test('user text is escaped', () => {
  const html = lenderExactView({lenderExact: {...lenderExactDefaults(), client_name: '<img src=x onerror=alert(1)>'}});
  assert.equal(html.includes('<img src=x'), false);
});

test('penalty page includes the lender-exact panel and the app wires its actions', () => {
  const views = readFileSync(new URL('../frontend/js/views.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../frontend/js/app.js', import.meta.url), 'utf8');
  const api = readFileSync(new URL('../frontend/js/api.js', import.meta.url), 'utf8');
  assert.match(views, /lenderExactView\(state\)/);
  for (const action of ['lender-exact-calc', 'lender-exact-letter', 'lender-exact-csv']) assert.match(app, new RegExp(action));
  assert.match(api, /\/api\/ratewatch\/penalty/);
  assert.equal(LENDERS[0][0], 'TD');
});
