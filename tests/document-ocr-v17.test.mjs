import {test} from 'node:test';
import assert from 'node:assert/strict';
import {api} from '../frontend/js/api.js';
import {state, resetState} from '../frontend/js/state.js';
import {getView} from '../frontend/js/views.js';
import {offlineDemoWorkspace} from '../frontend/js/offline-workspace.js';

test('offline demonstration is the illustrative RBC sample and stays explicitly hypothetical', () => {
  const demo = offlineDemoWorkspace();
  assert.equal(demo.mortgage.lender, 'RBC (illustrative sample)');
  assert.match(demo.notice, /Not an RBC document and not issued or endorsed by RBC/);
  resetState(demo); state.page = 'overview';
  assert.match(getView(), /It is not an RBC document and is not issued or endorsed by RBC/);
});
test('document screen accepts scans and exposes local OCR language selection', () => {
  resetState(offlineDemoWorkspace()); state.page = 'document';
  const view = getView();
  assert.match(view, /image\/png/);
  assert.match(view, /English and French/);
  assert.match(view, /Load sample scan/);
  assert.ok(!view.includes('Image-only scans require manual entry'));
});
test('OCR provenance escapes metadata and never fabricates unknown confidence', () => {
  resetState(offlineDemoWorkspace()); state.page = 'document';
  state.document = {pages: 1, fields: {}, ocr_pages: [{page: 1, version: '<script>x</script>', language: 'eng', mean_word_confidence: null}]};
  const view = getView();
  assert.match(view, /Local OCR/);
  assert.match(view, /&lt;script&gt;/);
  assert.ok(!view.includes('mean word confidence'));
});
test('scan API sends a multipart document to the same-origin bounded reader', async () => {
  const original = globalThis.fetch;
  try {
    let called;
    globalThis.fetch = async (path, options) => {called = {path, options}; return new Response('{}', {headers: {'Content-Type': 'application/json'}});};
    await api.documentRead(new File(['scan'], 'scan.png', {type: 'image/png'}), 'eng+fra');
    assert.equal(called.path, '/api/v17/documents/read?language=eng%2Bfra');
    assert.ok(called.options.body instanceof FormData);
    assert.equal(called.options.body.get('file').name, 'scan.png');
    assert.equal(called.options.cache, 'no-store');
  } finally {globalThis.fetch = original;}
});
