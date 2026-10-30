import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  BOOK_FIELDS, BOOK_CHOICES, validIsoDate, editBookDeal, clearBookState,
  selectedBookIndex, bookEditorView, bookDiagnosticsView,
  beginBookOperation, currentBookOperation,
} from '../frontend/js/book-editor.js';
import {resetState, state} from '../frontend/js/state.js';

const base = {
  deal_id: 'D1',
  borrower: 'Fictional Client',
  lender: 'TD',
  balance: 400000,
  contract_rate: 6.5,
  posted_rate: 8,
  discount: 1.5,
  term_months: 60,
  amort_months: 300,
  rate_type: 'fixed',
  balance_basis: 'current',
  amort_basis: 'remaining',
  closing_date: '2023-10-15',
  maturity_date: '2028-10-15',
  review_confirmed: true,
  issues: [],
};

test('all editable fields have distinct stable identifiers', () => {
  const keys = BOOK_FIELDS.map(field => field.key);
  assert.equal(new Set(keys).size, keys.length);
  assert.ok(keys.includes('balance_date'));
  assert.ok(keys.includes('payment'));
  assert.ok(keys.includes('posted_rate'));
  assert.ok(keys.includes('discount'));
  assert.ok(BOOK_CHOICES.frequency.some(([value]) => value === 'biweekly'));
});

test('ISO date validation rejects calendar rollover', () => {
  assert.equal(validIsoDate('2024-02-29'), true);
  assert.equal(validIsoDate('2023-02-29'), false);
  assert.equal(validIsoDate('2024-13-01'), false);
  assert.equal(validIsoDate('2024-04-31'), false);
  assert.equal(validIsoDate('03/04/2024'), false);
  assert.equal(validIsoDate('2101-01-01'), false);
  assert.equal(validIsoDate('1989-12-31'), false);
});

test('numeric edits are canonical percentage points', () => {
  const edited = editBookDeal(base, 'contract_rate', '0.25');
  assert.equal(edited.contract_rate, 0.25);
  assert.equal(edited.discount, 7.75);
  assert.equal(edited.review_confirmed, false);
  assert.equal(base.contract_rate, 6.5);
});

test('changing original posted rate reconciles the discount', () => {
  assert.equal(editBookDeal(base, 'posted_rate', '7.49').discount, 0.99);
  assert.equal(editBookDeal(base, 'posted_rate', '6').discount, null);
});

test('changing a field does not mutate the source or its evidence', () => {
  const source = {...base, evidence: {balance: {page: 1, excerpt: 'Balance'}}};
  const edited = editBookDeal(source, 'balance', '350000');
  assert.equal(edited.balance, 350000);
  assert.equal(source.balance, 400000);
  assert.deepEqual(edited.evidence, source.evidence);
});

test('invalid numeric edits do not silently fall back', () => {
  for (const value of ['NaN', 'Infinity', '-1', '400,000', '=1+1', '1e9', true]) {
    assert.throws(() => editBookDeal(base, 'balance', value));
  }
  assert.throws(() => editBookDeal(base, 'balance', '100000001'));
  assert.throws(() => editBookDeal(base, 'amort_months', '0'));
  assert.throws(() => editBookDeal(base, 'amort_months', '481'));
  assert.throws(() => editBookDeal(base, 'term_months', '1.5'));
});

test('clearing optional fields really clears them', () => {
  assert.equal(editBookDeal(base, 'posted_rate', '').posted_rate, null);
  assert.equal(editBookDeal(base, 'payment', '').payment, null);
  assert.equal(editBookDeal(base, 'balance_date', '').balance_date, null);
});

test('date edits require explicit valid dates', () => {
  assert.equal(editBookDeal(base, 'closing_date', '2024-02-29').closing_date, '2024-02-29');
  assert.throws(() => editBookDeal(base, 'closing_date', '2023-02-29'));
  assert.throws(() => editBookDeal(base, 'closing_date', '02/03/2024'));
});

test('only supported choice values are accepted', () => {
  assert.equal(editBookDeal(base, 'rate_type', 'variable').rate_type, 'variable');
  assert.equal(editBookDeal(base, 'rate_type', '').rate_type, null);
  assert.equal(editBookDeal(base, 'frequency', 'accelerated_weekly').frequency, 'accelerated_weekly');
  assert.throws(() => editBookDeal(base, 'frequency', 'daily'));
  assert.throws(() => editBookDeal(base, 'rate_type', 'unknown'));
  assert.throws(() => editBookDeal(base, 'unexpected_field', 'x'));
});

test('verification is explicit and cannot be enabled by a truthy string', () => {
  assert.equal(editBookDeal(base, 'review_confirmed', true).review_confirmed, true);
  assert.equal(editBookDeal(base, 'review_confirmed', false).review_confirmed, false);
  assert.throws(() => editBookDeal(base, 'review_confirmed', 'false'));
  assert.throws(() => editBookDeal(base, 'review_confirmed', 'true'));
});

test('fixing a field removes its stale import error but retains OCR provenance', () => {
  const record = {...base, issues: ['missing closing date', 'read by OCR: verify every value']};
  const edited = editBookDeal(record, 'closing_date', '2024-01-01');
  assert.deepEqual(edited.issues, ['read by OCR: verify every value']);
  assert.deepEqual(record.issues, ['missing closing date', 'read by OCR: verify every value']);
});

test('clearing the book removes borrower data and pending files', () => {
  const workspace = {
    page: 'book',
    mortgage: {balance: 400000},
    bookImport: {deals: [base]},
    bookReview: {results: [base]},
    bookError: 'previous',
    bookFilters: {target_rate: '4.5'},
    bookPendingFile: {name: 'private.csv'},
    bookDateOrder: 'day_first',
    bookEditingIndex: 1,
  };
  clearBookState(workspace);
  assert.deepEqual(Object.keys(workspace).sort(), ['bookEpoch', 'mortgage', 'page']);
  assert.equal(workspace.mortgage.balance, 400000);
});

test('workspace reset also clears imported books', () => {
  state.bookImport = {deals: [base]};
  state.bookReview = {results: [base]};
  state.bookPendingFile = {name: 'private.csv'};
  resetState({mortgage: {balance: 100000}, offers: []});
  assert.equal(state.bookImport, undefined);
  assert.equal(state.bookReview, undefined);
  assert.equal(state.bookPendingFile, undefined);
});

test('clearing the book invalidates every in-flight import or review', () => {
  const workspace = {bookImport: {deals: [base]}};
  const pending = beginBookOperation(workspace);
  assert.equal(currentBookOperation(workspace, pending), true);
  clearBookState(workspace);
  assert.equal(currentBookOperation(workspace, pending), false);
  assert.equal(workspace.bookImport, undefined);
});

test('the newest operation is the only one allowed to populate results', () => {
  const workspace = {};
  const older = beginBookOperation(workspace);
  const newer = beginBookOperation(workspace);
  assert.equal(currentBookOperation(workspace, older), false);
  assert.equal(currentBookOperation(workspace, newer), true);
  assert.equal(newer, older + 1);
});

test('operation guard tolerates an uninitialized or malformed epoch', () => {
  const workspace = {bookEpoch: 'not a sequence'};
  assert.equal(beginBookOperation(workspace), 1);
  assert.equal(currentBookOperation(workspace, 1), true);
  assert.equal(currentBookOperation(workspace, '1'), false);
});

test('selected deal indices are bounded', () => {
  assert.equal(selectedBookIndex({}), 0);
  assert.equal(selectedBookIndex({bookImport: {deals: [base]}, bookEditingIndex: 9}), 0);
  assert.equal(selectedBookIndex({bookImport: {deals: [base]}, bookEditingIndex: -1}), 0);
  assert.equal(selectedBookIndex({bookImport: {deals: [base, base]}, bookEditingIndex: 1}), 1);
});

test('empty workspace does not render bogus editing controls', () => {
  assert.equal(bookEditorView({}), '');
  assert.equal(bookEditorView({bookImport: {deals: []}}), '');
  assert.equal(bookDiagnosticsView({}), '');
});

test('all imported names and evidence are escaped', () => {
  const html = bookEditorView({bookImport: {deals: [{
    ...base,
    borrower: '<img src=x onerror=alert(1)>',
    lender: '"><script>bad</script>',
    issues: ['<script>note</script>'],
    evidence: {balance: {page: 1, excerpt: '<b>private</b>'}},
  }]}});
  assert.equal(html.includes('<script>'), false);
  assert.equal(html.includes('<img src=x'), false);
  assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('&lt;b&gt;private'));
});

test('editor controls are labelled and carry their row index', () => {
  const html = bookEditorView({bookImport: {deals: [base, {...base, deal_id: 'D2'}]}, bookEditingIndex: 1});
  assert.match(html, /for="book-edit-1-balance"/);
  assert.match(html, /id="book-edit-1-balance"/);
  assert.match(html, /data-index="1"/);
  assert.match(html, /Verified against the source document/);
  assert.match(html, /class="book-deal-confirm"/);
  assert.match(html, /value="1" selected/);
});

test('diagnostics display safe counts and duplicate reasons', () => {
  const html = bookDiagnosticsView({
    diagnostics: {blocked_deals: 2, estimated_methods: 1, issue_counts: {ocr_unverified: 2}},
    duplicates: [{deal_id: '<D1>', reason: '<duplicate>'}],
  });
  assert.match(html, /Blocked records: 2/);
  assert.match(html, /ocr unverified: 2/);
  assert.ok(html.includes('&lt;D1&gt;'));
  assert.equal(html.includes('<duplicate>'), false);
});

test('new controls and offline assets are wired into the real app', () => {
  const app = readFileSync(new URL('../frontend/js/app.js', import.meta.url), 'utf8');
  const sw = readFileSync(new URL('../frontend/service-worker.js', import.meta.url), 'utf8');
  const api = readFileSync(new URL('../frontend/js/api.js', import.meta.url), 'utf8');
  for (const name of ['book-clear', 'book-reimport', 'book-deal-field', 'book-deal-confirm', 'book-edit-select']) {
    assert.ok(app.includes(name), name);
  }
  assert.match(sw, /\/js\/book-editor\.js/);
  assert.match(api, /form\.append\('date_order'/);
});
