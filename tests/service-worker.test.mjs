import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {runInNewContext} from 'node:vm';

const workerSource = readFileSync(new URL('../frontend/service-worker.js', import.meta.url), 'utf8');

function environment({network = async () => new Response('fresh'), stored = null} = {}) {
  const handlers = new Map();
  const calls = {added: [], deleted: [], put: [], claim: 0, waiting: 0, network: 0};
  const cache = {
    addAll: async requests => {calls.added = [...requests].map(request => new URL(request.url).pathname);},
    put: async (key, response) => {calls.put.push({key, text: await response.text()});},
    match: async () => stored ? new Response(stored) : null,
  };
  const sandbox = {
    URL, Response, Request,
    fetch: async request => {calls.network++; return network(request);},
    caches: {
      open: async () => cache,
      keys: async () => ['other-app-cache', 'renewal-radar-shell-v16', 'renewal-radar-shell-v17', 'renewal-radar-shell-v18'],
      delete: async name => {calls.deleted.push(name);},
    },
    self: {
      location: {origin: 'http://localhost:8017'},
      addEventListener: (name, handler) => handlers.set(name, handler),
      skipWaiting: async () => {calls.waiting++;},
      clients: {claim: async () => {calls.claim++;}},
    },
  };
  runInNewContext(workerSource, sandbox);
  async function lifecycle(name) {
    let pending;
    handlers.get(name)({waitUntil: promise => {pending = promise;}});
    await pending;
  }
  async function fetchPath(path, options) {
    let response = null;
    handlers.get('fetch')({request: new Request(new URL(path, sandbox.self.location.origin), options), respondWith: promise => {response = promise;}});
    return response ? await response : null;
  }
  return {calls, lifecycle, fetchPath};
}

test('offline install includes every local application module and bundled font', async () => {
  const env = environment();
  await env.lifecycle('install');
  for (const path of env.calls.added) {
    const relative = path === '/' ? 'index.html' : path.slice(1);
    assert.ok(existsSync(new URL('../frontend/' + relative, import.meta.url)), path);
  }
  assert.ok(env.calls.added.includes('/js/helper-classifier.js'));
  assert.ok(env.calls.added.includes('/assets/fonts/Lato-Bold.ttf'));
  assert.equal(env.calls.waiting, 1);
});

test('the offline shell covers local JavaScript imports transitively', async () => {
  const env = environment();
  await env.lifecycle('install');
  const included = new Set(env.calls.added);
  for (const path of included) {
    if (!path.endsWith('.js')) continue;
    const file = new URL('../frontend' + path, import.meta.url);
    const source = readFileSync(file, 'utf8');
    for (const match of source.matchAll(/from\s+['"](.+?)['"]/g)) {
      const target = new URL(match[1], file);
      const relative = fileURLToPath(target).split('frontend')[1].replaceAll('\\', '/');
      assert.ok(included.has(relative), `${path} imports uncached ${relative}`);
    }
  }
});

test('activation preserves unrelated caches and removes only old Renewal Radar shells', async () => {
  const env = environment();
  await env.lifecycle('activate');
  assert.deepEqual(env.calls.deleted, ['renewal-radar-shell-v16', 'renewal-radar-shell-v17']);
  assert.equal(env.calls.claim, 1);
});

test('successful online responses refresh the shell cache', async () => {
  const env = environment();
  const response = await env.fetchPath('/js/helper-model.js');
  assert.equal(await response.text(), 'fresh');
  assert.deepEqual(env.calls.put, [{key: '/js/helper-model.js', text: 'fresh'}]);
});

test('offline requests receive the locally cached helper files', async () => {
  const env = environment({network: async () => {throw new Error('Offline');}, stored: 'cached helper'});
  const response = await env.fetchPath('/js/helper-model.js');
  assert.equal(response.status, 200);
  assert.equal(await response.text(), 'cached helper');
});

test('offline cold reload can use the cached application homepage', async () => {
  const env = environment({network: async () => {throw new Error('Offline');}, stored: '<main>Cached app</main>'});
  const response = await env.fetchPath('/');
  assert.match(await response.text(), /Cached app/);
});

test('missing cached files produce an explicit unavailable response', async () => {
  const env = environment({network: async () => {throw new Error('Offline');}});
  assert.equal((await env.fetchPath('/js/helper-model.js')).status, 503);
});

test('API, share, and credential-bearing requests never enter the shell cache', async () => {
  const env = environment();
  assert.equal(await env.fetchPath('/api/v17/market/snapshot'), null);
  assert.equal(await env.fetchPath('/shared/private-token'), null);
  assert.equal(await env.fetchPath('/', {headers: {'X-Case-Token': 'private'}}), null);
  assert.equal(await env.fetchPath('/', {headers: {Authorization: 'Bearer private'}}), null);
  assert.equal(await env.fetchPath('/', {method: 'POST'}), null);
  assert.equal(env.calls.network, 0);
  assert.equal(env.calls.put.length, 0);
});

test('external resources are not intercepted or cached', async () => {
  const env = environment();
  assert.equal(await env.fetchPath('https://other.invalid/js/helper-model.js'), null);
});

test('query strings are excluded from cache keys', async () => {
  const env = environment();
  await env.fetchPath('/?private=do-not-store');
  assert.equal(env.calls.put[0].key, '/');
  assert.ok(!JSON.stringify(env.calls.put).includes('do-not-store'));
});

test('HTTP errors cannot replace a good cached asset', async () => {
  const env = environment({network: async () => new Response('error', {status: 500})});
  assert.equal((await env.fetchPath('/js/helper-model.js')).status, 500);
  assert.equal(env.calls.put.length, 0);
});
