import {test} from 'node:test';
import assert from 'node:assert/strict';
import {answerLocalMortgageQuestion} from '../frontend/js/helper-answers.js';
import {helperWorkspace} from './helper-workspace.mjs';

const textOf = answer => answer.claims.map(claim => claim.text).join('\n');

test('contract rate answer cites the original document page', () => {
  const answer = answerLocalMortgageQuestion('What is my contract rate?', helperWorkspace());
  assert.equal(answer.intent, 'contract_rate');
  assert.match(textOf(answer), /4\.39%/);
  assert.equal(answer.evidence[0].page, 1);
  assert.equal(answer.networkRequired, false);
});

test('discount answer computes percentage points and basis points', () => {
  const answer = answerLocalMortgageQuestion('What is my contract discount?', helperWorkspace());
  assert.match(textOf(answer), /5\.69% - 4\.39% = 1\.3 percentage points/);
  assert.match(textOf(answer), /130 basis points/);
  assert.match(textOf(answer), /matches the stated discount/);
  assert.equal(new Set(answer.evidence.map(item => item.id)).size, answer.evidence.length);
});

test('discount mismatch remains visible instead of being corrected automatically', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.facts['original.contract_discount'].value = 1;
  const answer = answerLocalMortgageQuestion('What is my contract discount?', workspace);
  assert.match(textOf(answer), /does not match/);
  assert.ok(answer.claims.some(claim => claim.status === 'conflict'));
});

test('conflicting rates cannot produce a discount calculation', () => {
  const workspace = helperWorkspace();
  Object.assign(workspace.document.semantic_audit.facts['original.contract_rate'], {value: null, status: 'conflict'});
  const answer = answerLocalMortgageQuestion('Check my contract discount', workspace);
  assert.match(textOf(answer), /conflicting values/);
  assert.ok(!answer.claims.some(claim => claim.status === 'calculation'));
});

test('original and renewal discount components are not combined', () => {
  const workspace = helperWorkspace();
  delete workspace.document.semantic_audit.facts['original.contract_discount'];
  workspace.document.semantic_audit.facts['renewal.contract_discount'] = {field: 'contract_discount', scope: 'renewal', value: 1.3, status: 'resolved', evidence: []};
  const answer = answerLocalMortgageQuestion('What is my original contract discount?', workspace);
  assert.match(textOf(answer), /cannot find the contract discount/);
  assert.ok(!answer.claims.some(claim => claim.status === 'calculation'));
});

test('IRD explanation recognizes misspellings and conditional evidence', () => {
  const answer = answerLocalMortgageQuestion('Explain intrest rate differental', helperWorkspace());
  assert.equal(answer.intent, 'ird');
  assert.match(textOf(answer), /condition/);
  assert.match(textOf(answer), /written payout quote/);
  assert.match(textOf(answer), /not automatically/);
  assert.equal(answer.evidence[0].id, 'clause-ird');
});

test('absence of an IRD clause never implies a zero penalty', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.clauses = [];
  const answer = answerLocalMortgageQuestion('Explain IRD', workspace);
  assert.match(textOf(answer), /does not mean the penalty is zero/);
});

test('negated IRD wording does not waive every discharge fee', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.clauses[0].assertion = 'negated';
  assert.match(textOf(answerLocalMortgageQuestion('Explain IRD', workspace)), /does not establish that every discharge fee is waived/);
});

test('opposing IRD statements are identified as a conflict', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.clauses.push({...workspace.document.semantic_audit.clauses[0], id: 'ird-no', assertion: 'negated'});
  workspace.document.semantic_audit.clauses[0].assertion = 'mentioned';
  const answer = answerLocalMortgageQuestion('Explain IRD', workspace);
  assert.match(textOf(answer), /both mentions and negates/);
  assert.ok(answer.claims.some(claim => claim.status === 'conflict'));
});

test('illustrative IRD wording cannot become an operative penalty clause', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.clauses[0].assertion = 'example';
  assert.match(textOf(answerLocalMortgageQuestion('Explain IRD', workspace)), /only in an example/);
});

test('original funding and renewal dates are distinct answers', () => {
  const workspace = helperWorkspace();
  assert.match(textOf(answerLocalMortgageQuestion('When did my mortgage start?', workspace)), /2022-03-01/);
  const renewal = textOf(answerLocalMortgageQuestion('When is my renewal date?', workspace));
  assert.match(renewal, /2027-03-01/);
  assert.ok(!renewal.includes('2022-03-01'));
});

test('term answer includes months and the existing calendar check', () => {
  const answer = answerLocalMortgageQuestion('What is my term?', helperWorkspace());
  assert.match(textOf(answer), /36 months/);
  assert.match(textOf(answer), /3 years/);
  assert.match(textOf(answer), /Calculated term end: 2030-03-01/);
});

test('term and amortization answers use separate fields', () => {
  const workspace = helperWorkspace();
  const answer = answerLocalMortgageQuestion('What is the remaining amortization?', workspace);
  assert.match(textOf(answer), /240 months/);
  assert.match(textOf(answer), /20 years/);
  assert.ok(!textOf(answer).includes('36 months'));
});

test('offer expiry remains separate from maturity', () => {
  const answer = answerLocalMortgageQuestion('When does the offer expire?', helperWorkspace());
  assert.match(textOf(answer), /2027-02-15/);
  assert.ok(!textOf(answer).includes('2030-03-01'));
});

test('payment answer distinguishes document payment from model output', () => {
  const answer = answerLocalMortgageQuestion('What is my monthly payment?', helperWorkspace());
  assert.match(textOf(answer), /3,100\.00/);
  assert.match(textOf(answer), /existing analysis/);
  assert.match(textOf(answer), /modelled result/);
});

test('tax and insurance additions are surfaced when present', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.checks.push({id: 'document:tax_in_payment', detail: 'Separate property taxes from principal and interest.', status: 'review', evidence: []});
  assert.match(textOf(answerLocalMortgageQuestion('What is my monthly payment?', workspace)), /Separate property taxes/);
});

test('comparison answers retain offer status and existing analysis values', () => {
  const answer = answerLocalMortgageQuestion('Compare my mortgage renewal options', helperWorkspace());
  assert.match(textOf(answer), /12,050\.00/);
  assert.match(textOf(answer), /hypothetical/);
  assert.match(textOf(answer), /36 months/);
});

test('missing analysis cannot be replaced with invented savings', () => {
  const answer = answerLocalMortgageQuestion('Compare my mortgage renewal options', {});
  assert.match(textOf(answer), /cannot invent savings/);
});

test('review answers retain check ids for local followup decisions', () => {
  const answer = answerLocalMortgageQuestion('What needs review?', helperWorkspace());
  assert.equal(answer.intent, 'review');
  assert.equal(answer.claims[0].checkId, 'document:ird-inputs');
  assert.equal(answer.evidence[0].page, 2);
});

test('workspace-only answers identify values as inputs', () => {
  const answer = answerLocalMortgageQuestion('How much do I owe?', {mortgage: {balance: 300000}});
  assert.match(textOf(answer), /workspace input/);
  assert.equal(answer.evidence[0].source, 'workspace');
});

test('unspecified term context is not presented as a confirmed original rate', () => {
  const workspace = helperWorkspace();
  const fact = workspace.document.semantic_audit.facts['original.contract_rate'];
  delete workspace.document.semantic_audit.facts['original.contract_rate'];
  workspace.document.semantic_audit.facts['unspecified.contract_rate'] = {...fact, scope: 'unspecified'};
  assert.match(textOf(answerLocalMortgageQuestion('What is my contract rate?', workspace)), /term context needs confirmation/);
});

test('followup questions preserve the previous topic and change the scope', () => {
  const answer = answerLocalMortgageQuestion('What about the original', helperWorkspace(), {previousIntent: 'term'});
  assert.equal(answer.intent, 'term');
  assert.match(textOf(answer), /60 months/);
  assert.equal(answer.classificationReason, 'followup');
});

test('unknown questions return clarification without financial claims', () => {
  const answer = answerLocalMortgageQuestion('Who won the baseball game?', helperWorkspace());
  assert.equal(answer.intent, null);
  assert.equal(answer.evidence.length, 0);
  assert.ok(!textOf(answer).includes('4.39'));
});

test('all inference works with network access forbidden', () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = () => {throw new Error('Network is forbidden');};
  try {
    for (const question of ['Explain IRD', 'What is my term?', 'What needs review?', 'What is my contract discount?']) {
      const answer = answerLocalMortgageQuestion(question, helperWorkspace());
      assert.equal(answer.local, true);
      assert.equal(answer.networkRequired, false);
      assert.ok(answer.claims.length > 0);
    }
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('answers and evidence are deterministic for the same context', () => {
  const workspace = helperWorkspace();
  assert.deepEqual(answerLocalMortgageQuestion('What is my term?', workspace), answerLocalMortgageQuestion('What is my term?', workspace));
});
