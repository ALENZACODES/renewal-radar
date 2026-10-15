import {test} from 'node:test';
import assert from 'node:assert/strict';
import {semanticAuditView, semanticValue} from '../frontend/js/semantic-audit.js';
import {api} from '../frontend/js/api.js';
import {state, resetState} from '../frontend/js/state.js';
import {getView} from '../frontend/js/views.js';

function audit() {
  return {
    facts: {
      'original.contract_rate': {scope: 'original', field: 'contract_rate', value: 4.39, status: 'resolved', evidence: ['rate-original']},
      'renewal.offered_rate': {scope: 'renewal', field: 'offered_rate', value: 5.49, status: 'resolved', evidence: ['rate-renewal']},
      'renewal.maturity_date': {scope: 'renewal', field: 'maturity_date', value: null, status: 'unreadable', evidence: []},
    },
    mentions: [
      {id: 'rate-original', page: 1, line: 3, excerpt: 'Original contract rate: 4.39%'},
      {id: 'rate-renewal', page: 2, line: 1, excerpt: 'Renewal rate: 5.49%'},
    ],
    clauses: [],
    checks: [{id: 'discount', title: 'Contract discount', scope: 'original', status: 'incomplete', detail: 'Confirm the original posted rate.', evidence: ['rate-original']}],
    review_prompts: [{id: 'review-discount'}],
  };
}

test('empty semantic state does not add an empty section', () => {
  assert.equal(semanticAuditView(null), '');
});

test('term groups, values, and source locations are visible', () => {
  const html = semanticAuditView(audit());
  assert.match(html, /Original mortgage/);
  assert.match(html, /Renewal offer/);
  assert.match(html, /4\.39%/);
  assert.match(html, /5\.49%/);
  assert.match(html, /Page 1, line 3/);
  assert.match(html, /Source passages/);
  assert.match(html, /Unconfirmed/);
  assert.match(html, /1 review item</);
  assert.ok(!html.includes('undefined'));
});

test('error state is visible and escaped', () => {
  const html = semanticAuditView(null, '<img src=x onerror="bad()">');
  assert.match(html, /role="alert"/);
  assert.ok(!html.includes('<img'));
  assert.match(html, /&lt;img/);
});

test('all imported fields, evidence, titles, and formulas escape markup', () => {
  const result = audit();
  result.facts['renewal.maturity_date'].value = '<script>bad()</script>';
  result.mentions[0].excerpt = '<img src=x onerror="bad()">';
  result.checks[0].title = '<iframe src="x">';
  result.checks[0].detail = '<svg onload="bad()">';
  result.checks[0].formula = '<script>bad()</script>';
  const html = semanticAuditView(result);
  for (const tag of ['<script', '<img', '<iframe', '<svg']) assert.ok(!html.includes(tag));
  assert.match(html, /&lt;script/);
});

test('reviewer evidence has no fabricated page location', () => {
  const result = audit();
  result.mentions[0] = {...result.mentions[0], page: null, line: null, excerpt: 'Reviewer supplied a correction'};
  const html = semanticAuditView(result);
  assert.match(html, /Reviewer correction/);
  assert.ok(!html.includes('Page null'));
});

test('missing evidence references do not create broken passages', () => {
  const result = audit();
  result.facts['original.contract_rate'].evidence = ['missing'];
  result.checks = [];
  const html = semanticAuditView(result);
  assert.ok(!html.includes('undefined'));
  assert.ok(!html.includes('Page null'));
});

test('discounts and rates use distinct units and preserve zero', () => {
  assert.equal(semanticValue({field: 'contract_rate', value: 0}), '0%');
  assert.equal(semanticValue({field: 'contract_discount', value: 1.3}), '1.3 percentage points');
  assert.equal(semanticValue({field: 'term_months', value: 36}), '36 months');
  assert.equal(semanticValue({field: 'maturity_date', value: null}), 'Unconfirmed');
  assert.equal(semanticValue({field: 'maturity_date'}), 'Unconfirmed');
});

test('money values are formatted only when finite', () => {
  assert.match(semanticValue({field: 'balance', value: 480000}), /480,000\.00/);
  assert.equal(semanticValue({field: 'payment_amount', value: Infinity}), 'Unconfirmed');
});

test('empty successful audit renders without unbound values', () => {
  const html = semanticAuditView({});
  assert.match(html, /Contract details/);
  assert.match(html, /0 review items/);
  assert.ok(!html.includes('undefined'));
});

test('Letter X-Ray includes the audit result after an upload', () => {
  resetState({mortgage: {balance: 480000, offered_rate: 5.49, current_rate: 4.39, amortization_months: 240, term_months: 36, maturity_date: '2030-03-01', frequency: 'monthly', rate_type: 'fixed'}, offers: []});
  state.page = 'document';
  state.document = {fields: {}, pages: 2, warnings: [], semantic_audit: audit()};
  const html = getView();
  assert.match(html, /Mortgage contract details/);
  assert.match(html, /Original contract rate: 4\.39%/);
});

test('PDF audit request sends multipart content to the new route', async () => {
  const savedFetch = globalThis.fetch;
  let received;
  globalThis.fetch = async (path, options) => {
    received = {path, options};
    return new Response(JSON.stringify({provider: 'mortgage-document-semantic-auditor-v16'}), {headers: {'content-type': 'application/json'}});
  };
  try {
    const result = await api.pdfSemanticAudit(new Blob(['%PDF-test'], {type: 'application/pdf'}));
    assert.equal(received.path, '/api/v16/ocr/semantic-audit/pdf');
    assert.equal(received.options.method, 'POST');
    assert.ok(received.options.body instanceof FormData);
    assert.ok(received.options.body.has('file'));
    assert.equal(received.options.headers['Content-Type'], undefined);
    assert.equal(result.provider, 'mortgage-document-semantic-auditor-v16');
  } finally {
    globalThis.fetch = savedFetch;
  }
});
