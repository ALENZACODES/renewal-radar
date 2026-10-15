import {esc} from './ui.js';

const scopeLabels = {
  original: 'Original mortgage',
  renewal: 'Renewal offer',
  payout: 'Payout statement',
  unspecified: 'Term to confirm',
};
const statusLabels = {
  resolved: 'Read',
  consistent: 'Matches',
  conflict: 'Conflicting values',
  unreadable: 'Value to confirm',
  review: 'Review',
  incomplete: 'Missing details',
  observed: 'Observed',
};
const rateFields = new Set([
  'contract_rate', 'posted_rate', 'comparison_rate',
  'contract_discount', 'offered_rate', 'current_rate',
]);

export function semanticValue(fact) {
  const value = fact.value;
  if (value === null || value === undefined) return 'Unconfirmed';
  if (rateFields.has(fact.field)) {
    return `${value}${fact.field === 'contract_discount' ? ' percentage points' : '%'}`;
  }
  if (fact.field.endsWith('_months')) return `${value} months`;
  if (fact.field === 'balance' || fact.field === 'payment_amount') {
    const number = Number(value);
    return Number.isFinite(number)
      ? new Intl.NumberFormat('en-CA', {style: 'currency', currency: 'CAD'}).format(number)
      : 'Unconfirmed';
  }
  return String(value).replaceAll('_', ' ');
}

function statusText(status) {
  return statusLabels[status] || 'Review';
}

function evidenceIndex(audit) {
  return new Map([...(audit.mentions || []), ...(audit.clauses || [])]
    .map(item => [item.id, item]));
}

function evidenceList(references, ledger) {
  const items = references.map(id => ledger.get(id)).filter(Boolean);
  if (!items.length) return '';
  return `<details class="semantic-evidence"><summary>Source passages (${items.length})</summary>
    <ul>${items.map(item => `<li><span>${item.page == null ? 'Reviewer correction' : `Page ${esc(item.page)}, line ${esc(item.line)}`}</span>
      <p>${esc(item.excerpt || '')}</p></li>`).join('')}</ul></details>`;
}

function factsTable(audit, scope, ledger) {
  const facts = Object.values(audit.facts || {}).filter(fact => fact.scope === scope);
  if (!facts.length) return '';
  return `<div class="semantic-term"><h4>${esc(scopeLabels[scope] || scope)}</h4>
    <div class="table-scroll"><table class="semantic-facts"><thead>
      <tr><th scope="col">Detail</th><th scope="col">Value</th><th scope="col">Status</th></tr>
    </thead><tbody>${facts.map(fact => `<tr>
      <th scope="row">${esc(fact.field.replaceAll('_', ' '))}</th>
      <td>${esc(semanticValue(fact))}${evidenceList(fact.evidence || [], ledger)}</td>
      <td>${esc(statusText(fact.status))}</td>
    </tr>`).join('')}</tbody></table></div></div>`;
}

function checkList(audit, ledger) {
  const checks = audit.checks || [];
  if (!checks.length) return '';
  return `<div class="semantic-checks"><h4>Document checks</h4><ul>
    ${checks.map(check => `<li>
      <div class="semantic-check-heading"><strong>${esc(check.title)}</strong><span>${esc(statusText(check.status))}</span></div>
      <small>${esc(scopeLabels[check.scope] || 'Document')}</small>
      <p>${esc(check.detail)}</p>
      ${check.formula ? `<code>${esc(check.formula)}</code>` : ''}
      ${evidenceList(check.evidence || [], ledger)}
    </li>`).join('')}</ul></div>`;
}

export function semanticAuditView(audit, error = null) {
  if (!audit && !error) return '';
  if (!audit) {
    return `<section class="semantic-audit"><h3>Contract details</h3>
      <p role="alert">${esc(error)}</p></section>`;
  }
  const ledger = evidenceIndex(audit);
  const scopes = ['original', 'renewal', 'payout', 'unspecified'];
  const pending = (audit.review_prompts || []).length;
  return `<section class="semantic-audit" aria-label="Mortgage contract details">
    <div class="semantic-audit-heading"><h3>Contract details</h3><span>${pending} review item${pending === 1 ? '' : 's'}</span></div>
    <div class="semantic-term-grid">${scopes.map(scope => factsTable(audit, scope, ledger)).join('')}</div>
    ${checkList(audit, ledger)}
  </section>`;
}
