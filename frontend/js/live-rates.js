/** Live current rates: big banks and credit unions. Data from GET /api/ratewatch/live (primary + 3 backups per lender). */
import {esc, pageHead, button, dt} from './ui.js';

const TIER_CLASS = {primary: 'green-text', backup1: 'green-text', published: 'green-text', cache: '', archive: '', boc_typical: 'danger-text', unavailable: 'danger-text', not_public: ''};
const pct = v => (v == null ? '—' : `${Number(v).toFixed(2)}%`);

export function ageText(asOf, now = new Date()) {
  if (!asOf) return '';
  const t = Date.parse(asOf);
  if (Number.isNaN(t)) return String(asOf);                       // archive notes like "wayback 20261014"
  const mins = Math.max(0, Math.round((now - t) / 60000));
  if (mins < 60) return `${mins} min ago`;
  if (mins < 48 * 60) return `${Math.round(mins / 60)} h ago`;
  return `${Math.round(mins / 1440)} days ago`;
}

export function verificationBadge(v) {
  if (!v) return '<span class="muted">—</span>';
  const tip = (v.checks || []).map(c => `Level ${c.level} ${c.name}: ${c.ok ? 'pass' : 'fail'} (${c.detail})`).join('\n');
  const cls = v.level === 3 ? 'green-text' : v.level === 2 ? '' : 'danger-text';
  return `<span class="${cls}" title="${esc(tip)}">${'●'.repeat(v.level)}${'○'.repeat(3 - v.level)} ${v.level}/3</span>`;
}

function lenderRow(r, banks) {
  const f = r.five_year || {}, rates = r.rates || {};
  const term = m => rates[String(m)] || {};
  const best = m => { const t = term(m); return banks ? t.posted : Math.min(...Object.values(t).filter(v => v != null)); };
  const one = best(12), three = best(36);
  const tried = (r.tried || []).map(t => `${t.tier}: ${t.ok ? 'ok' : t.reason}`).join(' · ');
  return `<tr><td><strong>${esc(r.name)}</strong></td>
    <td>${pct(Number.isFinite(one) ? one : null)}</td><td>${pct(Number.isFinite(three) ? three : null)}</td>
    ${banks ? `<td>${pct(f.posted)}</td><td>${pct(f.special)}</td>` : `<td>${pct(f.advertised)}</td>`}
    <td class="${TIER_CLASS[r.tier] || ''}" title="${esc(tried)}">${esc(r.tier_label)}${r.lender_specific ? '' : ' *'}</td>
    <td>${verificationBadge(r.verification)}</td>
    <td>${esc(ageText(r.as_of))}</td>
    <td>${r.source_url ? `<a href="${esc(r.source_url)}" target="_blank" rel="noopener noreferrer">source</a>` : ''}</td></tr>`;
}

export function liveRatesView(workspace) {
  const b = workspace.liveRates;
  const head = pageHead('LIVE CURRENT RATES', 'Big banks and credit unions',
    'Each lender is read from its own published rates, with three automatic backups if a source fails.',
    button('Refresh now', 'live-rates-refresh', 'dark'));
  if (!b && workspace.liveRatesError) return `${head}<div class="notice warn" role="status">${esc(workspace.liveRatesError)}</div>`;
  if (!b) return `${head}<p>Loading current rates…</p>`;
  const note = workspace.liveRatesNote || workspace.liveRatesError;
  const noteHtml = note ? `<div class="notice mb" role="status">${esc(note)}</div>` : '';
  const hasRows = (b.banks || []).length || (b.credit_unions || []).length || (b.alternative_lenders || []).length;
  if (!hasRows) return `${head}${noteHtml}<section class="card padded"><h3>Collecting today’s rates</h3>
    <p>The server is reading each lender’s own published rates now (primary source plus three backups per lender).
    This page checks again every 15 seconds and fills in as soon as the first reading passes validation. No rate is ever estimated.</p></section>`;
  const a = b.anchor || {};
  const table = (rows, banks) => `<div class="table-scroll"><table class="compare-table"><thead><tr><th>Lender</th><th>1-yr</th><th>3-yr</th>
      ${banks ? '<th>5-yr posted</th><th>5-yr special</th>' : '<th>5-yr advertised</th>'}<th>Source</th><th>Verified</th><th>Updated</th><th></th></tr></thead>
      <tbody>${rows.map(r => lenderRow(r, banks)).join('')}</tbody></table></div>`;
  return `${head}${noteHtml}
    <div class="notice mb">${b.refreshed_at ? `Refreshed ${esc(ageText(b.refreshed_at))}${b.stale ? ' · refreshing in the background' : ''}.` : b.published?.refreshed_at ? `Showing the scheduled verified board from ${esc(ageText(b.published.refreshed_at))}; this server's own collection is running.` : 'First collection running in the background; reload in a few minutes.'}
      ${b.published?.lenders_filled && b.refreshed_at ? ` ${esc(b.published.lenders_filled)} lender(s) shown from the scheduled verified scrape (${esc(ageText(b.published.refreshed_at))}).` : ''}
      Bank of Canada big-six typical 5-year posted: <strong>${pct(a.boc_5y_posted)}</strong>
      ${a.boc_5y_posted_date ? `(${esc(dt(a.boc_5y_posted_date))})` : ''} · 5-year Government of Canada bond: <strong>${pct(a.goc_5y)}</strong></div>
    <section class="card padded"><h3>Big banks</h3>${table(b.banks || [], true)}</section>
    <section class="card padded mt2"><h3>Credit unions</h3>${table(b.credit_unions || [], false)}</section>
    <section class="card padded mt2"><h3>Private and B lenders</h3>
      <p class="fineprint">Most B lenders, trust companies and private lenders quote brokers directly and publish no public rates.
        They are checked through the same sources and backups, and show “Unavailable” until a public lender source exists.</p>
      ${table(b.alternative_lenders || [], false)}</section>
    <p class="fineprint mt"><strong>Verification, three levels.</strong> 1 Structure: the reading came from the lender’s own source and is internally consistent
      (5-year rate present, every rate 1–15%, no 3-year-plus special above posted, no jump over 2.5 points between terms of a year or more). 2 Market: plausible against Bank of Canada
      figures (big-six typical 5-year posted for banks, 5-year Government of Canada bond for others). 3 Corroborated: a second independent reading of the
      same lender agrees (another live source in the same run, or its previous reading within 0.50 points, 0.75 if over 3 days old). A scheduled scraper
      re-reads and re-verifies every lender every 6 hours. Hover the dots to see each check.</p>
    <p class="fineprint mt">Source order per lender: lender feed or page → second lender source (or its moved page, found automatically) →
      last good reading (up to 14 days) → newest web-archive copy. * Not lender-specific: shown only when every lender source fails.
      “Unavailable” means no reading passed validation; no rate is ever estimated. Credit-union “advertised” is the lowest
      5-year fixed rate on the lender’s own page. Hover a source label to see each attempt.</p>`;
}
