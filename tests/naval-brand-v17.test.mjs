import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const html = readFileSync(new URL('../frontend/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../frontend/assets/naval-academic.css', import.meta.url), 'utf8');
const worker = readFileSync(new URL('../frontend/service-worker.js', import.meta.url), 'utf8');

test('new brand assets are local and explicitly included in the offline shell', () => {
  for (const asset of ['/assets/naval-academic.css', '/assets/naval-waves.svg', '/assets/renewal-radar-naval-v17.png']) {
    assert.ok(worker.includes(asset), asset);
    assert.ok(readFileSync(new URL('../frontend' + asset, import.meta.url)).length > 100);
  }
  assert.ok(html.includes('/assets/naval-academic.css'));
});
test('the final logo is an actual PNG with alpha rather than a remote placeholder', () => {
  const file = readFileSync(new URL('../frontend/assets/renewal-radar-naval-v17.png', import.meta.url));
  assert.equal(file.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
  assert.ok([4, 6].includes(file[25]), 'PNG must retain an alpha channel');
  assert.ok(file.readUInt32BE(16) >= 512);
});
test('mobile navigation exposes both financial tools and the remaining workspaces', () => {
  const mobile = html.slice(html.indexOf('<nav id="mobile-nav"'));
  for (const page of ['market', 'penalty', 'switch', 'negotiate', 'plan', 'report']) {
    assert.ok(mobile.includes(`data-nav="${page}"`), page);
  }
  assert.ok(mobile.includes('aria-label="More workspaces"'));
});
test('reference-inspired graphics retain the original product identity and readable local fonts', () => {
  assert.match(html, /Renewal<span>Radar/);
  assert.ok(!html.includes('Penn Engineering'));
  assert.ok(!html.includes('fonts.googleapis.com'));
  assert.match(css, /font-family: 'Inter'/);
  assert.match(css, /#990000/);
  assert.match(css, /data-theme='dark'/);
  assert.ok(!css.includes('gradient('));
});
