/** Lender-exact penalty check: uses /api/ratewatch (live lender rates, lender-specific rules, PDF letter). */
import {esc, money, percent, field, options, button, dt} from './ui.js';

export const LENDERS = [['TD', 'TD (exact lender method)'], ['RBC', 'RBC'], ['Scotiabank', 'Scotiabank'], ['BMO', 'BMO'],
  ['CIBC', 'CIBC'], ['National Bank', 'National Bank'], ['Simplii', 'Simplii'], ['ATB', 'ATB'],
  ['Desjardins', 'Desjardins'], ['Tangerine', 'Tangerine']];

export function lenderExactDefaults() {
  return {lender: 'TD', balance: '400000', contract_rate: '4.89', term_months: '60', start: '2023-10-15',
    maturity: '2028-10-15', discount: '2.00', amort_months: '300', payout: '', client_name: '', language: 'en'};
}

const num = v => (v === '' || v == null || !Number.isFinite(Number(v))) ? null : Number(v);

/** Body for POST /api/ratewatch/penalty. Empty optional fields are omitted, never sent as 0. */
export function lenderExactRequest(input) {
  const i = {...lenderExactDefaults(), ...(input || {})};
  const body = {lender: i.lender, balance: num(i.balance), contract_rate: num(i.contract_rate),
    term_months: num(i.term_months), start: i.start, amort_months: num(i.amort_months) ?? 300};
  if (i.maturity) body.maturity = i.maturity;
  if (num(i.discount) != null) body.discount = num(i.discount);
  if (i.payout) body.payout = i.payout;
  return body;
}

export function lenderExactView(workspace) {
  const i = {...lenderExactDefaults(), ...(workspace.lenderExact || {})};
  const r = workspace.lenderExactResult, f = workspace.lenderExactForecast, cheap = workspace.lenderExactCheapest;
  const exact = r?.status === 'exact-method';
  const stat = (label, value, note) => `<div class="penalty-stat"><span>${esc(label)}</span><strong>${esc(value)}</strong><small>${esc(note)}</small></div>`;
  const f2 = (label, key, value, type = 'number') => field(label, key, value, type, '', 'lx-field');
  return `<section class="card padded mt2" id="lender-exact"><div class="card-head"><div><div class="eyebrow">LENDER-SPECIFIC RULES</div>
      <h3>Lender-exact check</h3><p>Uses the lender's published posted rates today and its own prepayment rules where they are known.</p></div>
      <div class="btnrow">${button('Calculate', 'lender-exact-calc', 'dark')}${button('Letter (PDF)', 'lender-exact-letter', 'ghost')}${button('CSV', 'lender-exact-csv', 'ghost')}</div></div>
    <div class="form-grid mt">
      ${field('Lender', 'lender', options(LENDERS, i.lender), 'select', '', 'lx-field')}
      ${f2('Balance (CAD)', 'balance', i.balance)}${f2('Contract rate (%)', 'contract_rate', i.contract_rate)}
      ${f2('Original term (months)', 'term_months', i.term_months)}${f2('Term start', 'start', i.start, 'date')}
      ${f2('Maturity date', 'maturity', i.maturity, 'date')}${f2('Original discount (points)', 'discount', i.discount)}
      ${f2('Remaining amortization (months)', 'amort_months', i.amort_months)}${f2('Payout date (blank = today)', 'payout', i.payout, 'date')}
      ${f2('Client name (letter only)', 'client_name', i.client_name, 'text')}
      ${field('Letter language', 'language', options([['en', 'English'], ['fr', 'Français']], i.language), 'select', '', 'lx-field')}
    </div>
    ${workspace.lenderExactError ? `<div class="notice warn mt" role="status">${esc(workspace.lenderExactError)}</div>` : ''}
    ${r ? `<div class="penalty-output-heading mt"><div><div class="eyebrow">${exact ? 'EXACT LENDER METHOD' : 'ESTIMATE'}</div>
        <h2>${r.method === 'matured' ? 'Matured: no prepayment charge' : esc(money(r.penalty, 2))}</h2></div>
        <span class="penalty-status">${exact ? 'Lender rules reproduced' : 'Method not yet verified for this lender'}</span></div>
      ${r.method === 'matured' ? '' : `<div class="penalty-summary-grid">
        ${stat('Three months’ interest', money(r.three_month, 2), 'Contract rate')}
        ${stat('Interest rate differential', money(r.ird, 2), `${r.compare_term}-month posted ${percent(r.compare_posted)} less ${r.discount}% discount`)}
        ${stat('Months remaining', String(r.remaining_months), 'Lender convention')}
        ${stat('Lowest in next year', cheap?.penalty == null ? '—' : money(cheap.penalty, 2), cheap?.date ? dt(cheap.date) : 'If posted rates hold')}
      </div>`}
      ${f?.transitions?.length ? `<h3 class="mt2">When the charge changes</h3><div class="penalty-transitions">${f.transitions.slice(0, 6).map(t =>
        `<div><strong>${esc(dt(t.payout))}</strong><b>${esc(t.compare_term)}-month rate</b><span>${esc(money(t.penalty, 2))}</span></div>`).join('')}</div>` : ''}
      <p class="fineprint mt">Rates: ${esc(r.rates_source || '')}. ${exact ? 'This lender’s calculation method was reproduced from its own published calculator.' : 'Treat as an estimate until confirmed by the lender’s written payout statement.'} Fees are not included.</p>` : ''}
  </section>`;
}
