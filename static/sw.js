// PRESSFLOW 서비스 워커: 화면 뼈대만 캐시(오프라인 시 안내), 데이터(API)는 항상 서버에서 가져온다.
const V = 'pressflow-v1';
const SHELL = ['/', '/static/app.css', '/static/app.js', '/static/logo.svg'];
self.addEventListener('install', e => { e.waitUntil(caches.open(V).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener('activate', e => { e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== V).map(k => caches.delete(k)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.pathname.startsWith('/api/') || u.pathname.startsWith('/files/')) return;
  e.respondWith(fetch(e.request).then(r => { if (r.ok && u.origin === location.origin) { const c = r.clone(); caches.open(V).then(x => x.put(e.request, c)); } return r; })
    .catch(() => caches.match(e.request).then(m => m || new Response('PRESSFLOW 서버가 꺼져 있습니다. 바탕화면의 PRESSFLOW 아이콘으로 다시 실행하세요.', { status: 503, headers: { 'content-type': 'text/plain; charset=utf-8' } }))));
});
