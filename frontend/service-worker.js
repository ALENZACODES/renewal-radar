const shellCacheName = 'renewal-radar-shell-v19';
const shellAssets = [
  '/', '/assets/app.css', '/assets/public-service.css',
  '/assets/naval-academic.css', '/assets/naval-waves.svg', '/assets/renewal-radar-naval-v17.png',
  '/assets/fonts/NotoSans-Variable.ttf', '/assets/fonts/Lato-Regular.ttf', '/assets/fonts/Lato-Bold.ttf',
  '/assets/fonts/InterVariable.woff2', '/assets/vendor/echarts-6.1.0.min.js',
  '/js/app.js', '/js/api.js', '/js/state.js',
  '/js/ui.js', '/js/views.js', '/js/semantic-audit.js',
  '/js/helper-model.js', '/js/helper-classifier.js', '/js/helper-context.js',
  '/js/helper-answers.js', '/js/helper-review.js', '/js/helper-conversation.js',
  '/js/helper-view.js', '/js/helper-panel.js', '/js/offline-workspace.js', '/js/rate-tracker.js',
  '/js/chart-data.js', '/js/chart-options.js', '/js/chart-view.js', '/js/chart-runtime.js',
  '/js/penalty-studio.js', '/js/lender-exact.js', '/js/live-rates.js', '/js/broker-book.js',
];
const allowedPaths = new Set(shellAssets);

self.addEventListener('install', event => {
  event.waitUntil((async () => {
    const cache = await caches.open(shellCacheName);
    await cache.addAll(shellAssets.map(path => new Request(new URL(path, self.location.origin), {cache: 'reload'})));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith('renewal-radar-shell-') && name !== shellCacheName) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || !allowedPaths.has(url.pathname)) return;
  if (request.headers.has('Authorization') || request.headers.has('X-Case-Token') || request.headers.has('X-OCR-Review-Token')) return;
  event.respondWith((async () => {
    const cache = await caches.open(shellCacheName);
    const key = url.pathname;
    try {
      const response = await fetch(request, {cache: 'no-store'});
      if (response.ok && response.type !== 'opaque') {
        await cache.put(key, response.clone());
      }
      return response;
    } catch {
      const cached = await cache.match(key);
      if (cached) return cached;
      return new Response('Offline application file unavailable. Reopen once while the local server is running.', {
        status: 503, headers: {'Content-Type': 'text/plain'},
      });
    }
  })());
});
