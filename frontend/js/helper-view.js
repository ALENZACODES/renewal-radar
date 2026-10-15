import {esc} from './ui.js';
import {safeHelperContext} from './helper-context.js';

const suggestions = [
  'What is my contract rate?', 'What is my contract discount?',
  'Explain IRD', 'When did my mortgage start?',
  'What is my term?', 'What needs review?',
];
const topicQuestions = {
  contract_rate: 'What is my contract rate?', posted_rate: 'What is the posted rate?',
  discount: 'What is my contract discount?', ird: 'Explain IRD',
  mortgage_date: 'When did my mortgage start?', renewal_date: 'When is my renewal date?',
  maturity: 'What is the maturity date?', term: 'What is my term?',
  amortization: 'What is the remaining amortization?', renewal_rate: 'What is my offered renewal rate?',
  current_rate: 'What is my current rate?', balance: 'How much do I owe?',
  payment: 'What is my monthly payment?', comparison: 'Compare my mortgage renewal options.',
  expiry: 'When does the offer expire?', review: 'What needs review?', help: 'What can I ask?',
  market: 'What is the latest Bank of Canada policy rate?',
};

function sourcePassages(evidence) {
  if (!Array.isArray(evidence) || !evidence.length) return '';
  return `<details class="helper-evidence"><summary>Evidence (${evidence.length})</summary><ul>
    ${evidence.map(item => `<li><strong>${item.source === 'workspace' ? 'Workspace input' : item.source === 'official-market' ? 'Official market source' : item.page == null ? 'Reviewer correction' : `Page ${esc(item.page)}, line ${esc(item.line)}`}</strong>
      <p>${esc(item.excerpt || '')}</p></li>`).join('')}
  </ul></details>`;
}

function renderAnswer(answer) {
  return `<div class="helper-answer">
    ${(answer?.claims || []).map(claim => `<p>${esc(claim.text)}</p>`).join('')}
    ${sourcePassages(answer?.evidence)}
    ${(answer?.suggestions || []).length ? `<div class="helper-suggestions">${answer.suggestions.map(item =>
      `<button type="button" data-helper-suggestion="${esc(topicQuestions[item.id] || item.label)}">${esc(item.label)}</button>`).join('')}</div>` : ''}
  </div>`;
}

function reviewItems(snapshot) {
  const records = snapshot.records.filter(record => record.type === 'check' && ['review', 'conflict', 'incomplete'].includes(record.status));
  if (!records.length) return '';
  return `<details class="helper-review-list"><summary>Document review (${records.length})</summary>
    <ul>${records.map(record => `<li>
      <div><strong>${esc(record.label)}</strong>${record.stale ? '<small>Evidence changed</small>' : ''}</div>
      <label>Decision<select data-helper-decision="${esc(record.id)}">
        ${[['unreviewed', 'Not reviewed'], ['reviewed', 'Reviewed'], ['needs_followup', 'Needs follow-up']].map(([value, label]) => `<option value="${value}"${record.decision === value ? ' selected' : ''}>${label}</option>`).join('')}
      </select></label>
      <label>Note<input type="text" maxlength="500" data-helper-note="${esc(record.id)}" value="${esc(record.note)}" /></label>
    </li>`).join('')}</ul>
  </details>`;
}

export function renderHelperPanel(conversation, workspace, {open = false, error = null, draft = ''} = {}) {
  if (!open) return '';
  const review = conversation.review.snapshot(workspace);
  const fingerprint = safeHelperContext(workspace).fingerprint;
  return `<section class="helper-panel" role="dialog" aria-modal="false" aria-label="Mortgage helper">
    <header class="helper-heading"><div><h2>Mortgage helper</h2><span>On this device</span></div>
      <button type="button" data-helper-command="close" class="helper-icon" aria-label="Close mortgage helper" title="Close">&times;</button></header>
    <div class="helper-history" role="log" aria-live="polite" aria-relevant="additions text">
      ${conversation.messages.length ? conversation.messages.map(message => `<article class="helper-message helper-${esc(message.role)}">
        <small>${message.role === 'user' ? 'You' : message.answer?.contextFingerprint !== fingerprint ? 'Mortgage helper (earlier inputs)' : 'Mortgage helper'}</small>
        ${message.role === 'user' ? `<p>${esc(message.text)}</p>` : renderAnswer(message.answer)}
      </article>`).join('') : '<p class="helper-greeting">What would you like to check?</p>'}
    </div>
    ${conversation.messages.length ? '' : `<div class="helper-suggestions">${suggestions.map(question => `<button type="button" data-helper-suggestion="${esc(question)}">${esc(question)}</button>`).join('')}</div>`}
    ${error || conversation.storageError ? `<p class="helper-error" role="alert">${esc(error || conversation.storageError)}</p>` : ''}
    <form class="helper-composer" id="helper-question-form">
      <label class="helper-question-label" for="helper-question">Question</label>
      <textarea id="helper-question" name="question" rows="2" maxlength="1000" required placeholder="Ask about your mortgage">${esc(draft)}</textarea>
      <button type="submit" class="helper-icon helper-send" aria-label="Ask mortgage helper" title="Ask">&uarr;</button>
    </form>
    ${reviewItems(review)}
    <footer class="helper-footer">
      <label><input type="checkbox" data-helper-remember${conversation.remember ? ' checked' : ''} />Keep this conversation on this device</label>
      <div class="helper-footer-actions">
        <button type="button" data-helper-command="export" title="Download conversation and review notes">Export</button>
        <button type="button" data-helper-command="clear" title="Clear conversation and review notes">Clear conversation</button>
      </div>
    </footer>
  </section>`;
}
