import {test} from 'node:test';
import assert from 'node:assert/strict';
import {LocalMortgageConversation, helperStorageKey} from '../frontend/js/helper-conversation.js';
import {LocalEvidenceReview, helperReviewTargets} from '../frontend/js/helper-review.js';
import {helperWorkspace, memoryStorage} from './helper-workspace.mjs';

const clock = () => '2026-10-14T12:00:00.000Z';

function conversation(workspace = helperWorkspace(), storage = memoryStorage()) {
  return new LocalMortgageConversation({getWorkspace: () => workspace, storage, clock});
}

test('conversation remains in memory before storage consent', () => {
  const storage = memoryStorage();
  const helper = conversation(helperWorkspace(), storage);
  helper.ask('What is my contract rate?');
  assert.equal(helper.messages.length, 2);
  assert.equal(storage.writes.length, 0);
  assert.equal(helper.remember, false);
});

test('opt-in writes a bounded transcript without case credentials', () => {
  const storage = memoryStorage();
  const workspace = helperWorkspace();
  workspace.caseRecord = {access_token: 'PRIVATE_TOKEN'};
  const helper = conversation(workspace, storage);
  helper.ask('What is my contract rate?');
  helper.setRemember(true);
  const stored = storage.getItem(helperStorageKey);
  assert.ok(stored.includes('local-mortgage-conversation-v17'));
  assert.ok(!stored.includes('PRIVATE_TOKEN'));
});

test('opting out removes local data while retaining current in-memory conversation', () => {
  const storage = memoryStorage();
  const helper = conversation(helperWorkspace(), storage);
  helper.setRemember(true);
  helper.ask('Explain IRD');
  helper.setRemember(false);
  assert.equal(storage.getItem(helperStorageKey), null);
  assert.equal(helper.messages.length, 2);
});

test('storage failures preserve answers and expose the failure', () => {
  const helper = conversation(helperWorkspace(), {setItem() {throw new Error('Quota exceeded');}});
  helper.setRemember(true);
  const answer = helper.ask('What is my term?');
  assert.equal(answer.intent, 'term');
  assert.equal(helper.storageError, 'Quota exceeded');
  assert.equal(helper.messages.length, 2);
});

test('privacy-restricted storage is optional', () => {
  const helper = conversation(helperWorkspace(), null);
  helper.setRemember(true);
  assert.match(helper.storageError, /unavailable/);
  assert.equal(helper.ask('Explain IRD').intent, 'ird');
});

test('clear removes transcript and review notes without retaining document evidence in storage', () => {
  const storage = memoryStorage();
  const helper = conversation(helperWorkspace(), storage);
  helper.setRemember(true);
  helper.ask('Explain IRD');
  helper.decide('check:document:ird-inputs', 'needs_followup', 'Ask the lender');
  helper.clear();
  assert.equal(helper.messages.length, 0);
  assert.equal(helper.review.events.length, 0);
  assert.equal(storage.getItem(helperStorageKey), null);
});

test('followup keeps the last understood topic rather than the last unknown query', () => {
  const helper = conversation();
  helper.ask('What is my term?');
  helper.ask('Who won the baseball game?');
  const answer = helper.ask('What about the original');
  assert.equal(answer.intent, 'term');
  assert.match(answer.claims[0].text, /60 months/);
});

test('history is bounded and message identifiers remain monotonic', () => {
  const helper = conversation();
  for (let count = 0; count < 25; count++) helper.ask('What is my term?');
  assert.equal(helper.messages.length, 40);
  assert.equal(helper.messages[0].id, 11);
  assert.equal(helper.messages.at(-1).id, 50);
});

test('invalid questions do not partially append conversation messages', () => {
  const helper = conversation();
  assert.throws(() => helper.ask(' '));
  assert.throws(() => helper.ask('x'.repeat(1001)));
  assert.equal(helper.messages.length, 0);
});

test('transcript export is a detached snapshot', () => {
  const helper = conversation();
  helper.ask('Explain IRD');
  const packet = helper.packet();
  packet.messages[0].text = 'Changed outside the conversation';
  assert.equal(helper.messages[0].text, 'Explain IRD');
  assert.equal(packet.cloudModelUsed, false);
  assert.equal(packet.rawOcrIncluded, false);
});

test('persisted conversations and review notes restore without a server', () => {
  const storage = memoryStorage();
  const first = conversation(helperWorkspace(), storage);
  first.setRemember(true);
  first.ask('What is my contract rate?');
  first.decide('check:document:ird-inputs', 'needs_followup', 'Need comparison rate');
  const second = conversation(helperWorkspace(), storage);
  assert.equal(second.restore(), true);
  assert.equal(second.remember, true);
  assert.equal(second.messages.length, 2);
  assert.equal(second.review.snapshot(helperWorkspace()).summary.followup, 1);
  second.ask('What is my term?');
  assert.equal(second.messages.at(-1).id, 4);
});

for (const data of ['{invalid', '{}', JSON.stringify({provider: 'other', messages: []}), 'x'.repeat(180001)]) {
  test(`invalid stored conversation is contained (${data.length} bytes)`, () => {
    const storage = memoryStorage();
    storage.setItem(helperStorageKey, data);
    const helper = conversation(helperWorkspace(), storage);
    assert.equal(helper.restore(), false);
    assert.equal(helper.messages.length, 0);
    assert.ok(helper.storageError);
  });
}

test('malformed restored messages cannot replace a current conversation', () => {
  const storage = memoryStorage();
  const helper = conversation(helperWorkspace(), storage);
  helper.ask('Explain IRD');
  const packet = helper.packet();
  packet.messages[0].text = 'x'.repeat(1001);
  storage.setItem(helperStorageKey, JSON.stringify(packet));
  assert.equal(helper.restore(), false);
  assert.equal(helper.messages[0].text, 'Explain IRD');
});

test('storage consent must be an explicit boolean', () => {
  const helper = conversation();
  assert.throws(() => helper.setRemember('yes'));
  assert.equal(helper.remember, false);
});

test('review marks retain the source signature and a bounded note', () => {
  const workspace = helperWorkspace();
  const review = new LocalEvidenceReview({clock});
  const record = review.decide(workspace, 'check:document:ird-inputs', 'needs_followup', 'Confirm comparison rate');
  assert.match(record.signature, /^[a-f0-9]{8}$/);
  assert.equal(record.recordedAt, clock());
  assert.equal(review.snapshot(workspace).summary.followup, 1);
});

test('reviewed conflicts remain conflicts and are not certified', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.checks[0].status = 'conflict';
  const review = new LocalEvidenceReview({clock});
  review.decide(workspace, 'check:original:rate-discount', 'reviewed', 'Discuss with lender');
  const snapshot = review.snapshot(workspace);
  assert.equal(snapshot.summary.conflicts, 1);
  assert.equal(snapshot.summary.reviewed, 1);
  assert.equal(snapshot.lenderCertification, false);
});

test('source changes invalidate only the affected reviewer marks', () => {
  const workspace = helperWorkspace();
  const review = new LocalEvidenceReview({clock});
  review.decide(workspace, 'fact:original.contract_rate', 'reviewed');
  review.decide(workspace, 'fact:renewal.offered_rate', 'reviewed');
  workspace.document.semantic_audit.facts['original.contract_rate'].value = 4.2;
  const snapshot = review.snapshot(workspace);
  assert.equal(snapshot.summary.stale, 1);
  assert.equal(snapshot.records.find(item => item.id === 'fact:original.contract_rate').decision, 'unreviewed');
  assert.equal(snapshot.records.find(item => item.id === 'fact:renewal.offered_rate').decision, 'reviewed');
});

test('evidence changes invalidate a decision even when the value agrees', () => {
  const workspace = helperWorkspace();
  const review = new LocalEvidenceReview({clock});
  review.decide(workspace, 'fact:original.contract_rate', 'reviewed');
  workspace.document.semantic_audit.facts['original.contract_rate'].evidence.push('new-source');
  assert.equal(review.snapshot(workspace).summary.stale, 1);
});

test('unknown decisions and vanished targets are rejected without changing revision', () => {
  const review = new LocalEvidenceReview({clock});
  assert.throws(() => review.decide(helperWorkspace(), 'missing', 'reviewed'));
  assert.throws(() => review.decide(helperWorkspace(), 'fact:original.contract_rate', 'approved'));
  assert.throws(() => review.decide(helperWorkspace(), 'fact:original.contract_rate', 'reviewed', 'x'.repeat(501)));
  assert.equal(review.revision, 0);
});

test('review event retention is bounded and export keeps latest decisions', () => {
  const workspace = helperWorkspace();
  const review = new LocalEvidenceReview({clock});
  for (let count = 0; count < 205; count++) review.decide(workspace, 'fact:original.contract_rate', 'reviewed', String(count));
  assert.equal(review.events.length, 200);
  assert.equal(review.export(workspace).events[0].revision, 6);
  assert.equal(review.snapshot(workspace).records.find(item => item.id === 'fact:original.contract_rate').note, '204');
});

test('restoring out-of-order review events does not corrupt existing notes', () => {
  const workspace = helperWorkspace();
  const review = new LocalEvidenceReview({clock});
  review.decide(workspace, 'fact:original.contract_rate', 'reviewed', 'Original note');
  const packet = review.export(workspace);
  packet.events.push({...packet.events[0], note: 'Invalid duplicate'});
  assert.throws(() => review.restore(packet));
  assert.equal(review.events.length, 1);
  assert.equal(review.events[0].note, 'Original note');
});

test('review exports exclude raw OCR and expose stable target identities', () => {
  const workspace = helperWorkspace();
  workspace.document.preview = [{text: 'PRIVATE_TEXT'}];
  const review = new LocalEvidenceReview({clock});
  assert.ok(!JSON.stringify(review.export(workspace)).includes('PRIVATE_TEXT'));
  assert.ok(helperReviewTargets(workspace).has('fact:renewal.term_months'));
});
