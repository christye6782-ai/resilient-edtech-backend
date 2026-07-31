const CACHE_NAME = 'resilient-cache-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/css/style.css',
  '/js/app.js'
];

self.addEventListener('install', (ev) => {
  ev.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (ev) => {
  ev.waitUntil(self.clients.claim());
});

self.addEventListener('fetch', (ev) => {
  ev.respondWith(caches.match(ev.request).then((r) => r || fetch(ev.request)));
});
