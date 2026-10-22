import {test} from 'node:test';
import assert from 'node:assert/strict';
import {LocalMortgageConversation} from '../frontend/js/helper-conversation.js';
import {renderHelperPanel} from '../frontend/js/helper-view.js';
import {loadInitialWorkspace, offlineDemoWorkspace, registerOfflineShell, readLocalHelperStorage} from '../frontend/js/offline-workspace.js';
import {helperWorkspace} from './helper-workspace.mjs';

test('closed helper panel creates no hidden duplicate interactive controls', () => {
  assert.equal(renderHelperPanel(new LocalMortgageConversation(), {}), '');
});

test('empty helper has an accessible question form and starter questions', () => {
  const html = renderHelperPanel(new LocalMortgageConversation(), {}, {open: true});
  assert.match(html, /aria-label="Mortgage helper"/);
  assert.match(html, /id="helper-question-form"/);
  assert.match(html, /maxlength="1000"/);
  assert.match(html, /What is my contract discount/);
  assert.match(html, /data-helper-remember/);
});

test('document answers render source evidence and review controls', () => {
  const workspace = helperWorkspace();
  const helper = new LocalMortgageConversation({getWorkspace: () => workspace});
  helper.ask('What is my contract rate?');
  const html = renderHelperPanel(helper, workspace, {open: true});
  assert.match(html, /4\.39%/);
  assert.match(html, /Page 1, line 1/);
  assert.match(html, /data-helper-decision/);
  assert.match(html, /Document review/);
});

test('imported questions, evidence, notes, drafts, and errors are escaped', () => {
  const workspace = helperWorkspace();
  workspace.document.semantic_audit.mentions[0].excerpt = '<img src=x onerror="bad()">';
  const helper = new LocalMortgageConversation({getWorkspace: () => workspace});
  helper.ask('What is my contract rate? <script>bad()</script>');
  helper.decide('check:document:ird-inputs', 'needs_followup', '<svg onload="bad()">');
  const html = renderHelperPanel(helper, workspace, {open: true, error: '<iframe>', draft: '</textarea><script>bad()</script>'});
  for (const tag of ['<script', '<img', '<svg', '<iframe']) assert.ok(!html.includes(tag));
  assert.match(html, /&lt;/);
});

test('earlier answers are visibly marked after workspace values change', () => {
  const workspace = helperWorkspace();
  const helper = new LocalMortgageConversation({getWorkspace: () => workspace});
  helper.ask('What is my term?');
  workspace.document.semantic_audit.facts['renewal.term_months'].value = 48;
  assert.match(renderHelperPanel(helper, workspace, {open: true}), /earlier inputs/);
});

test('storage failure is shown without hiding the conversation', () => {
  const helper = new LocalMortgageConversation({storage: null});
  helper.setRemember(true);
  helper.ask('Explain IRD');
  const html = renderHelperPanel(helper, {}, {open: true});
  assert.match(html, /role="alert"/);
  assert.match(html, /storage is unavailable/);
  assert.match(html, /written payout quote/);
});

test('stale review decisions are marked after their source changes', () => {
  const workspace = helperWorkspace();
  const helper = new LocalMortgageConversation({getWorkspace: () => workspace});
  helper.decide('check:document:ird-inputs', 'reviewed');
  workspace.document.semantic_audit.checks[2].detail = 'Different comparison-rate requirement';
  assert.match(renderHelperPanel(helper, workspace, {open: true}), /Evidence changed/);
});

test('offline bootstrap works when demo requests cannot reach the server', async () => {
  const result = await loadInitialWorkspace({demo: async () => {throw new Error('Offline');}});
  assert.equal(result.offline, true);
  assert.equal(result.data.mortgage.balance, 480000);
  assert.match(result.data.notice, /RBC illustrative sample, offline/);
});

test('online bootstrap preserves the server provided workspace', async () => {
  const data = {mortgage: {balance: 300000}, offers: []};
  const result = await loadInitialWorkspace({demo: async () => data});
  assert.equal(result.offline, false);
  assert.equal(result.data, data);
});

test('offline sample is a fresh object for each boot', () => {
  const first = offlineDemoWorkspace();
  first.mortgage.balance = 1;
  assert.equal(offlineDemoWorkspace().mortgage.balance, 480000);
});

test('unavailable service worker support is handled without an exception', async () => {
  assert.deepEqual(await registerOfflineShell({}), {registered: false, reason: 'unsupported'});
});

test('offline shell registration uses the same-origin root scope', async () => {
  let called;
  const registration = {};
  const result = await registerOfflineShell({serviceWorker: {register: async (...args) => {called = args; return registration;}}});
  assert.deepEqual(called, ['/service-worker.js', {scope: '/'}]);
  assert.equal(result.registered, true);
  assert.equal(result.registration, registration);
});

test('service worker registration failure does not disable the helper', async () => {
  const result = await registerOfflineShell({serviceWorker: {register: async () => {throw new Error('Disabled');}}});
  assert.equal(result.registered, false);
  assert.equal(result.reason, 'unavailable');
});

test('a privacy-restricted local storage getter is contained', () => {
  assert.equal(readLocalHelperStorage({get localStorage() {throw new Error('Denied');}}), null);
  assert.equal(readLocalHelperStorage(null), null);
});
