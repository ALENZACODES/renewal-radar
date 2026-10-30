import {test} from 'node:test';
import assert from 'node:assert/strict';
import {safeHelperContext, findHelperFact, helperFactEvidence, helperCheckEvidence, requestedHelperScopes, helperFingerprint} from '../frontend/js/helper-context.js';
import {helperWorkspace} from './helper-workspace.mjs';

test('document facts take precedence over editable workspace values', () => {
  const workspace = helperWorkspace();
  workspace.mortgage.offered_rate = 6.49;
  const fact = findHelperFact(safeHelperContext(workspace), 'offered_rate');
  assert.equal(fact.value, 5.49);
  assert.equal(fact.source, 'document');
  assert.equal(fact.scope, 'renewal');
});

test('conflicted document evidence cannot fall back to a convenient input', () => {
  const workspace = helperWorkspace();
  Object.assign(workspace.document.semantic_audit.facts['renewal.offered_rate'], {value: null, status: 'conflict'});
  const fact = findHelperFact(safeHelperContext(workspace), 'offered_rate');
  assert.equal(fact.value, null);
  assert.equal(fact.status, 'conflict');
  assert.equal(fact.source, 'document');
});

test('original and renewal rates do not cross scope boundaries', () => {
  const context = safeHelperContext(helperWorkspace());
  assert.equal(findHelperFact(context, 'contract_rate', ['renewal']), null);
  assert.equal(findHelperFact(context, 'contract_rate', ['original']).value, 4.39);
});

test('workspace input evidence is explicitly distinguished from a document', () => {
  const context = safeHelperContext({mortgage: {balance: 300000}});
  const fact = findHelperFact(context, 'balance');
  assert.equal(fact.status, 'input');
  assert.equal(fact.source, 'workspace');
  assert.equal(helperFactEvidence(context, fact)[0].excerpt, 'Current workspace input');
});

test('unknown account fields and access tokens never enter the context', () => {
  const workspace = helperWorkspace();
  workspace.caseRecord = {access_token: 'PRIVATE_ACCESS_TOKEN'};
  workspace.mortgage.account_number = '123456789';
  workspace.document.semantic_audit.facts['original.account_number'] = {field: 'account_number', scope: 'original', value: '123456789'};
  const serialized = JSON.stringify(safeHelperContext(workspace));
  assert.ok(!serialized.includes('PRIVATE_ACCESS_TOKEN'));
  assert.ok(!serialized.includes('123456789'));
  assert.ok(!serialized.includes('account_number'));
});

test('the helper does not retain raw page text or PDF bytes', () => {
  const workspace = helperWorkspace();
  workspace.document.preview = [{text: 'PRIVATE_RAW_PAGE_TEXT'}];
  workspace.document.fileBytes = 'PRIVATE_PDF_BYTES';
  workspace.document.semantic_audit.pages = [{text: 'PRIVATE_RAW_PAGE_TEXT'}];
  const serialized = JSON.stringify(safeHelperContext(workspace));
  assert.ok(!serialized.includes('PRIVATE_RAW_PAGE_TEXT'));
  assert.ok(!serialized.includes('PRIVATE_PDF_BYTES'));
});

test('missing source ids are excluded from the evidence list', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.facts['original.contract_rate'].evidence.push('missing');
  const context = safeHelperContext(workspace);
  const refs = helperFactEvidence(context, findHelperFact(context, 'contract_rate', ['original']));
  assert.equal(refs.length, 1);
  assert.equal(refs[0].page, 1);
});

test('page and line locations are bounded and excerpts are truncated', () => {
  const workspace = helperWorkspace();
  Object.assign(workspace.document.semantic_audit.mentions[0], {page: 300, line: 2000, excerpt: 'x'.repeat(1000)});
  const evidence = safeHelperContext(workspace).ledger['mention-original.contract_rate'];
  assert.equal(evidence.page, null);
  assert.equal(evidence.line, null);
  assert.equal(evidence.excerpt.length, 240);
});

for (const value of [NaN, Infinity, -1, 31, '4.39', true]) {
  test(`invalid rate value ${String(value)} cannot support an answer`, () => {
    const workspace = helperWorkspace();
    workspace.document.semantic_audit.facts['original.contract_rate'].value = value;
    const fact = safeHelperContext(workspace).facts['original.contract_rate'];
    assert.equal(fact.value, null);
    assert.equal(fact.status, 'unreadable');
  });
}

for (const value of ['2026-13-01', '2026-02-30', '03/04/2026', '2026-00-01']) {
  test(`invalid or ambiguous date ${value} remains unconfirmed`, () => {
    const workspace = helperWorkspace();
    workspace.document.semantic_audit.facts['renewal.maturity_date'].value = value;
    assert.equal(safeHelperContext(workspace).facts['renewal.maturity_date'].value, null);
  });
}

test('zero percent is retained as a valid rate', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.facts['original.contract_rate'].value = 0;
  assert.equal(safeHelperContext(workspace).facts['original.contract_rate'].value, 0);
});

test('noninteger durations and unrecognized frequencies are rejected', () => {
  const context = safeHelperContext({mortgage: {term_months: 36.5, amortization_months: 601, frequency: 'daily'}});
  assert.deepEqual(context.inputs, {});
});

test('unexpected source URL schemes are not retained', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.sources.push({title: 'Bad', url: 'javascript:alert(1)'});
  workspace.document.semantic_audit.sources.push({title: 'Unknown', url: 'https://other.invalid/'});
  assert.equal(safeHelperContext(workspace).sources.length, 1);
});

test('context fingerprint changes when source facts or analysis change', () => {
  const workspace = helperWorkspace();
  const original = safeHelperContext(workspace).fingerprint;
  workspace.document.semantic_audit.facts['original.contract_rate'].value = 4.2;
  assert.notEqual(safeHelperContext(workspace).fingerprint, original);
  const second = safeHelperContext(workspace).fingerprint;
  workspace.analysis.scenarios[0].loan.regular_payment = 3200;
  assert.notEqual(safeHelperContext(workspace).fingerprint, second);
});

test('workspace snapshot does not mutate the source', () => {
  const workspace = helperWorkspace();
  const copy = structuredClone(workspace);
  safeHelperContext(workspace);
  assert.deepEqual(workspace, copy);
});

test('null and missing contexts are usable for general definitions', () => {
  assert.deepEqual(safeHelperContext(null).facts, {});
  assert.deepEqual(safeHelperContext().scenarios, []);
  assert.equal(findHelperFact(safeHelperContext(), 'contract_rate'), null);
});

test('malformed optional collections do not break local inference', () => {
  const context = safeHelperContext({document: {semantic_audit: {mentions: {}, clauses: {}, checks: {}, sources: {}}}});
  assert.deepEqual(context.ledger, {});
  assert.deepEqual(context.clauses, []);
});

test('scope selection respects single and combined term questions', () => {
  const defaults = ['renewal', 'original'];
  assert.deepEqual(requestedHelperScopes('original mortgage', defaults), ['original']);
  assert.deepEqual(requestedHelperScopes('new renewal', defaults), ['renewal']);
  assert.deepEqual(requestedHelperScopes('payout rate', defaults), ['payout']);
  assert.deepEqual(requestedHelperScopes('compare original and renewal', defaults), defaults);
});

test('check references resolve only to present source passages', () => {
  const context = safeHelperContext(helperWorkspace());
  const refs = helperCheckEvidence(context, {evidence: ['clause-ird', 'missing']});
  assert.equal(refs.length, 1);
  assert.equal(refs[0].id, 'clause-ird');
});

test('fingerprints are deterministic local identifiers', () => {
  assert.equal(helperFingerprint({rate: 4.39}), helperFingerprint({rate: 4.39}));
  assert.match(helperFingerprint({rate: 4.39}), /^[a-f0-9]{8}$/);
});
