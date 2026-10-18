import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {brokerBookView, bookReviewRequest, bookDefaults} from '../frontend/js/broker-book.js';

test('review request omits blank filters and keeps numbers', () => {
  const b = bookReviewRequest([{deal_id: 'x'}], {...bookDefaults(), closed_from: '2023-01-01', target_rate: ''});
  assert.equal(b.closed_from, '2023-01-01');
  assert.equal('closed_to' in b, false);
  assert.equal('target_rate' in b, false);
  assert.equal(b.new_term_months, 60);
  assert.equal(bookReviewRequest([], {target_rate: '4.25'}).target_rate, 4.25);
});

const review = {deals_reviewed: 2, total_net_benefit: 5960, best_offer: {lender: 'Synergy', rate: 4.59},
  top_offers: [{lender: 'Synergy', rate: 4.59}, {lender: 'beem', rate: 4.69}],
  summary: {strong: 1, possible: 0, needs_data: 1},
  results: [
    {status: 'strong', deal_id: 'F-1', borrower: 'Client <A>', lender: 'TD', method_status: 'exact-method', contract_rate: 6.5,
     maturity_date: '2028-10-16', penalty: {penalty: 12000}, best_offer: {lender: 'Synergy', rate: 4.59}, net_benefit: 5960,
     years_saved_same_payment: 3.1, recommendation: 'Break now', issues: []},
    {status: 'needs_data', deal_id: 'F-2', lender: 'RBC', method_status: 'estimate', contract_rate: 5.5, three_month_floor: 5400,
     recommendation: 'Need discount', issues: ['IRD not computed']}]};

test('results show status, exact/estimate, floor and escape user text', () => {
  const html = brokerBookView({bookImport: {deals: [{}, {}], mapping: {lender: 'Lender Name'}, ignored_columns: ['Notes']}, bookReview: review});
  assert.match(html, /Strong/);
  assert.match(html, /exact lender method/);
  assert.match(html, /estimate/);
  assert.match(html, /≥ /);
  assert.match(html, /Lender Name/);
  assert.equal(html.includes('Client <A>'), false);
  assert.match(html, /Synergy 4\.59%/);
});

test('page is registered, cached offline and wired', () => {
  const html = readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
  const sw = readFileSync(new URL('../frontend/service-worker.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../frontend/js/app.js', import.meta.url), 'utf8');
  const api = readFileSync(new URL('../frontend/js/api.js', import.meta.url), 'utf8');
  assert.match(html, /data-nav="book"/);
  assert.match(sw, /\/js\/broker-book\.js/);
  for (const a of ['book-review', 'book-export', 'book-sample', 'book-file', 'book-ocr']) assert.match(app, new RegExp(a));
  assert.match(api, /\/api\/broker\/book\/review/);
});
