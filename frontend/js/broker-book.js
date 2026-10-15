/** Broker book review: import a book of funded deals, find who saves by breaking now. Uses /api/broker/book/*. */
import {esc, pageHead, button, money, dt} from './ui.js';
import {bookEditorView,bookDiagnosticsView} from './book-editor.js';

const STATUS = {
  strong: ['Strong', 'green-text'], possible: ['Possible', 'green-text'], renewal_window: ['Renewal window', ''],
  needs_data: ['Needs data', ''], no_opportunity: ['No saving', 'danger-text'], insufficient_data: ['Incomplete', 'danger-text'],
  matured: ['Matured', ''], not_started: ['Not funded yet', ''],
};

export function bookDefaults() {
  return {closed_from: '', closed_to: '', lender: '', target_rate: '', new_term_months: '60', fees: '0'};
}

/** Request body for POST /api/broker/book/review. Blank filters are omitted. */
export function bookReviewRequest(deals, filters) {
  const f = {...bookDefaults(), ...(filters || {})};
  const body = {deals, new_term_months: Number(f.new_term_months) || 60, fees: Number(f.fees) || 0};
  if (f.closed_from) body.closed_from = f.closed_from;
  if (f.closed_to) body.closed_to = f.closed_to;
  if (f.lender) body.lender = f.lender;
  if (f.target_rate !== '' && Number.isFinite(Number(f.target_rate)) && Number(f.target_rate) > 0) body.target_rate = Number(f.target_rate);
  return body;
}

const pct = v => (v == null ? '—' : `${Number(v).toFixed(2)}%`);

function resultRow(r) {
  const [label, cls] = STATUS[r.status] || [r.status, ''];
  const p = r.penalty || {}, b = r.best_offer || {};
  const issues = (r.issues || []).map(i => `<li>${esc(i)}</li>`).join('');
  return `<tr><td class="${cls}"><strong>${esc(label)}</strong></td><td>${esc(r.deal_id)}<small>${esc(r.borrower || '')}</small></td>
    <td>${esc(r.lender || '—')}<small>${esc(r.method_status === 'exact-method' ? 'exact lender method' : 'estimate')}</small></td>
    <td>${pct(r.contract_rate)}<small>${r.maturity_date ? 'to ' + esc(dt(r.maturity_date)) : ''}</small></td>
    <td>${p.penalty == null ? (r.three_month_floor ? '≥ ' + money(r.three_month_floor) : '—') : money(p.penalty)}</td>
    <td>${b.rate ? pct(b.rate) : '—'}<small>${esc(b.lender || '')}</small></td>
    <td>${r.net_benefit == null ? '—' : money(r.net_benefit)}</td>
    <td>${r.years_saved_same_payment == null ? '—' : esc(String(r.years_saved_same_payment)) + ' yrs'}</td>
    <td>${esc(r.recommendation || '')}${issues ? `<details><summary>Notes</summary><ul>${issues}</ul></details>` : ''}</td></tr>`;
}

export function brokerBookView(workspace) {
  const f = {...bookDefaults(), ...(workspace.bookFilters || {})};
  const imp = workspace.bookImport, rv = workspace.bookReview;
  const input = (label, key, value, type = 'text') =>
    `<div class="field"><label>${esc(label)}</label><input class="book-filter" data-key="${esc(key)}" type="${type}" value="${esc(value)}"/></div>`;
  const head = pageHead('BROKER BOOK REVIEW', 'Who should break their mortgage now?',
    'Import your funded deals, then see which clients save interest and years by breaking at today’s rates.',
    button('Run review', 'book-review', 'dark') + button('Export CSV', 'book-export', 'ghost') + button('Sample file', 'book-sample', 'ghost') + button('Clear book', 'book-clear', 'ghost'));
  return `${head}
    <section class="card padded"><h3>1. Import deals</h3>
      <div class="field mt"><label for="book-date-order">Numeric date order</label>
        <select id="book-date-order" class="book-date-order">
          <option value=""${!workspace.bookDateOrder?' selected':''}>Detect unambiguous dates</option>
          <option value="day_first"${workspace.bookDateOrder==='day_first'?' selected':''}>Day / month / year</option>
          <option value="month_first"${workspace.bookDateOrder==='month_first'?' selected':''}>Month / day / year</option>
        </select></div>
      ${button('Reimport', 'book-reimport', 'ghost')}
      <div class="form-grid mt">
        <div class="field"><label>Export from broker software (CSV, TSV or JSON)</label><input type="file" class="book-file" accept=".csv,.tsv,.txt,.json"/></div>
        <div class="field"><label>Mortgage documents to read by OCR (PDF or scans)</label><input type="file" class="book-ocr" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" multiple/></div>
      </div>
      ${workspace.bookError ? `<div class="notice warn mt" role="status">${esc(workspace.bookError)}</div>` : ''}
      ${imp ? `<p class="mt">${esc(String(imp.deals.length))} deals loaded${imp.with_issues ? `, ${esc(String(imp.with_issues))} with notes` : ''}.</p>
        ${imp.mapping ? `<details><summary>Column mapping (check before relying on results)</summary><ul>${Object.entries(imp.mapping).map(([k, v]) => `<li><b>${esc(k)}</b> ← ${esc(v)}</li>`).join('')}</ul>
        ${imp.ignored_columns?.length ? `<p class="fineprint">Not used: ${esc(imp.ignored_columns.join(', '))}</p>` : ''}
        ${imp.unmapped_fields?.length ? `<p class="fineprint danger-text">Not found: ${esc(imp.unmapped_fields.join(', '))}</p>` : ''}</details>` : ''}` : ''}
      ${bookEditorView(workspace)}
    </section>
    <section class="card padded mt2"><h3>2. Filter and assumptions</h3><div class="form-grid mt">
      ${input('Closed from', 'closed_from', f.closed_from, 'date')}${input('Closed to', 'closed_to', f.closed_to, 'date')}
      ${input('Lender contains', 'lender', f.lender)}${input('Target rate % (blank = best live offer)', 'target_rate', f.target_rate, 'number')}
      ${input('New term (months)', 'new_term_months', f.new_term_months, 'number')}${input('Switch fees (CAD)', 'fees', f.fees, 'number')}
    </div></section>
    ${rv ? `<section class="card padded mt2"><div class="card-head"><div><h3>3. Opportunities</h3>
        <p>${esc(String(rv.deals_reviewed))} deals reviewed · ${esc(String(rv.summary.strong))} strong · ${esc(String(rv.summary.possible))} possible ·
        ${esc(String(rv.summary.needs_data))} need data · potential net saving ${money(rv.total_net_benefit)}</p>
        <p class="fineprint">Best offer used: ${rv.best_offer ? `${esc(rv.best_offer.lender)} ${pct(rv.best_offer.rate)}` : 'none available'}
        ${rv.top_offers?.length ? ` · next: ${rv.top_offers.slice(1).map(o => `${esc(o.lender)} ${pct(o.rate)}`).join(', ')}` : ''}</p></div></div>
      ${bookDiagnosticsView(rv)}
      <div class="table-scroll"><table class="compare-table"><thead><tr><th>Status</th><th>Deal</th><th>Lender</th><th>Rate</th><th>Penalty today</th>
        <th>Best rate</th><th>Net saving</th><th>Years saved*</th><th>Recommendation</th></tr></thead>
        <tbody>${rv.results.map(resultRow).join('')}</tbody></table></div>
      <p class="fineprint mt">Net saving = interest saved over the shorter of the remaining term and the new term, minus the penalty and fees.
        *Hypothetical years saved at the same payment frequency, assuming unchanged lifetime rates, with penalty and fees added to the loan. TD, Scotiabank and CIBC penalties follow each bank's own
        calculator; other lenders are estimates until the payout statement confirms them. Nothing you import is stored.</p></section>` : ''}`;
}
