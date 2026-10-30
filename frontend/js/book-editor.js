import {esc} from './ui.js';

export const BOOK_FIELDS = [
  {key: 'lender', label: 'Lender', type: 'text'},
  {key: 'balance', label: 'Balance (CAD)', type: 'number', min: 0.01, max: 100000000},
  {key: 'contract_rate', label: 'Contract rate (%)', type: 'number', min: 0.000001, max: 30},
  {key: 'posted_rate', label: 'Original posted rate (%)', type: 'number', min: 0.000001, max: 30},
  {key: 'discount', label: 'Original discount (points)', type: 'number', min: 0, max: 10},
  {key: 'term_months', label: 'Original term (months)', type: 'number', min: 1, max: 120, integer: true},
  {key: 'closing_date', label: 'Closing date', type: 'date'},
  {key: 'maturity_date', label: 'Maturity date', type: 'date'},
  {key: 'amort_months', label: 'Amortization (months)', type: 'number', min: 1, max: 480, integer: true},
  {key: 'payment', label: 'Regular payment (CAD)', type: 'number', min: 0.01, max: 1000000},
  {key: 'balance_date', label: 'Statement balance date', type: 'date'},
];

export const BOOK_CHOICES = {
  rate_type: [
    ['', 'Not confirmed'],
    ['fixed', 'Fixed'],
    ['variable', 'Variable'],
  ],
  balance_basis: [
    ['current', 'Current statement balance'],
    ['original', 'Original advance'],
  ],
  amort_basis: [
    ['remaining', 'Remaining amortization'],
    ['original', 'Original amortization'],
  ],
  frequency: [
    ['', 'Not confirmed'],
    ['monthly', 'Monthly'],
    ['semi_monthly', 'Twice monthly'],
    ['biweekly', 'Biweekly'],
    ['weekly', 'Weekly'],
    ['accelerated_biweekly', 'Accelerated biweekly'],
    ['accelerated_weekly', 'Accelerated weekly'],
  ],
};

const CHOICE_LABELS = {
  rate_type: 'Rate type',
  balance_basis: 'Balance basis',
  amort_basis: 'Amortization basis',
  frequency: 'Payment frequency',
};

export function validIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + 'T12:00:00Z');
  return Number.isFinite(parsed.valueOf())
    && parsed.toISOString().slice(0, 10) === value
    && value >= '1990-01-01' && value <= '2100-12-31';
}

export function editBookDeal(deal, key, raw) {
  if (!deal || typeof deal !== 'object') throw new Error('Select an imported deal.');
  const field = BOOK_FIELDS.find(item => item.key === key);
  const choices = BOOK_CHOICES[key];
  let value;
  if (key === 'review_confirmed') {
    if (typeof raw !== 'boolean') throw new Error('Verification must be checked or unchecked.');
    return {...deal, review_confirmed: raw};
  }
  if (choices) {
    if (!choices.some(([candidate]) => candidate === raw)) throw new Error('Choose a listed value.');
    value = raw || null;
  } else if (!field) {
    throw new Error('This field is not editable.');
  } else if (raw === '' || raw == null) {
    value = null;
  } else if (field.type === 'number') {
    if (typeof raw === 'boolean' || !/^[+]?\d+(\.\d+)?$/.test(String(raw))) {
      throw new Error(field.label + ' must be a number.');
    }
    value = Number(raw);
    if (!Number.isFinite(value) || value < field.min || value > field.max || (field.integer && !Number.isInteger(value))) {
      throw new Error(field.label + ' is outside its allowed range.');
    }
  } else if (field.type === 'date') {
    if (!validIsoDate(String(raw))) throw new Error('Choose a valid date between 1990 and 2100.');
    value = String(raw);
  } else {
    value = String(raw).trim().slice(0, 160) || null;
  }
  const result = {...deal, [key]: value, review_confirmed: false};
  const label = key.replaceAll('_', ' ');
  result.issues = (deal.issues || []).filter(issue => !(
    typeof issue === 'string' && issue.includes(label)
    && /^(missing|invalid|ambiguous)/.test(issue)
  ));
  if (key === 'posted_rate' || key === 'contract_rate') {
    if (result.posted_rate != null && result.contract_rate != null) {
      result.discount = result.posted_rate >= result.contract_rate
        ? Number((result.posted_rate - result.contract_rate).toFixed(6)) : null;
    }
  }
  return result;
}

export function clearBookState(workspace) {
  beginBookOperation(workspace);
  for (const key of ['bookImport', 'bookReview', 'bookError', 'bookFilters', 'bookEditingIndex', 'bookPendingFile', 'bookDateOrder']) {
    delete workspace[key];
  }
}

export function beginBookOperation(workspace) {
  workspace.bookEpoch = Number.isSafeInteger(workspace.bookEpoch) ? workspace.bookEpoch + 1 : 1;
  return workspace.bookEpoch;
}

export function currentBookOperation(workspace, ticket) {
  return workspace.bookEpoch === ticket;
}

export function selectedBookIndex(workspace) {
  const count = workspace.bookImport?.deals?.length || 0;
  const index = Number(workspace.bookEditingIndex ?? 0);
  return Number.isInteger(index) && index >= 0 && index < count ? index : 0;
}

function fieldControl(field, deal, index) {
  const id = 'book-edit-' + index + '-' + field.key;
  const value = deal[field.key] ?? '';
  const bounds = field.type === 'number'
    ? ' min="' + field.min + '" max="' + field.max + '" step="' + (field.integer ? '1' : 'any') + '"' : '';
  return '<div class="field"><label for="' + id + '">' + esc(field.label) + '</label>'
    + '<input id="' + id + '" class="book-deal-field" data-field="' + field.key
    + '" data-index="' + index + '" type="' + field.type + '" value="' + esc(value) + '"' + bounds + '/></div>';
}

function choiceControl(key, deal, index) {
  const id = 'book-edit-' + index + '-' + key;
  const options = BOOK_CHOICES[key].map(([value, label]) => '<option value="' + esc(value) + '"'
    + (value === (deal[key] || '') ? ' selected' : '') + '>' + esc(label) + '</option>').join('');
  return '<div class="field"><label for="' + id + '">' + esc(CHOICE_LABELS[key]) + '</label>'
    + '<select id="' + id + '" class="book-deal-field" data-field="' + key
    + '" data-index="' + index + '">' + options + '</select></div>';
}

export function bookEditorView(workspace) {
  const deals = workspace.bookImport?.deals || [];
  if (!deals.length) return '';
  const index = selectedBookIndex(workspace);
  const deal = deals[index];
  const options = deals.map((item, row) => '<option value="' + row + '"'
    + (row === index ? ' selected' : '') + '>'
    + esc(item.deal_id || 'Deal ' + (row + 1)) + (item.borrower ? ' / ' + esc(item.borrower) : '') + '</option>').join('');
  const evidence = Object.entries(deal.evidence || {}).filter(([, item]) => item && typeof item === 'object');
  return '<details class="mt" id="book-editor"><summary>Review imported fields</summary>'
    + '<div class="field mt"><label for="book-edit-select">Deal</label>'
    + '<select id="book-edit-select" class="book-edit-select">' + options + '</select></div>'
    + '<div class="form-grid mt">'
    + BOOK_FIELDS.map(field => fieldControl(field, deal, index)).join('')
    + Object.keys(BOOK_CHOICES).map(key => choiceControl(key, deal, index)).join('')
    + '</div><label class="mt"><input type="checkbox" class="book-deal-confirm" data-index="' + index + '"'
    + (deal.review_confirmed ? ' checked' : '') + '/> Verified against the source document</label>'
    + (deal.issues?.length ? '<ul>' + deal.issues.map(issue => '<li>' + esc(issue) + '</li>').join('') + '</ul>' : '')
    + (evidence.length ? '<details class="mt"><summary>Document evidence</summary><dl>'
      + evidence.map(([field, item]) => '<dt>' + esc(field.replaceAll('_', ' ')) + '</dt><dd>Page '
        + esc(item.page ?? '') + ': ' + esc(item.excerpt || '') + '</dd>').join('') + '</dl></details>' : '')
    + '</details>';
}

export function bookDiagnosticsView(review) {
  const diagnostics = review?.diagnostics;
  if (!diagnostics) return '';
  const duplicates = review.duplicates || [];
  const counts = Object.entries(diagnostics.issue_counts || {});
  return '<details class="mt"><summary>Review diagnostics</summary><ul>'
    + '<li>Blocked records: ' + esc(diagnostics.blocked_deals || 0) + '</li>'
    + '<li>Estimated penalty methods: ' + esc(diagnostics.estimated_methods || 0) + '</li>'
    + counts.map(([code, count]) => '<li>' + esc(code.replaceAll('_', ' ')) + ': ' + esc(count) + '</li>').join('')
    + duplicates.map(item => '<li>' + esc(item.deal_id) + ': ' + esc(item.reason) + '</li>').join('')
    + '</ul></details>';
}
