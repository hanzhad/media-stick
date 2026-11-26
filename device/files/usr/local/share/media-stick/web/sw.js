const CACHE_NAME = 'ms-panel-v2-4';
const PRECACHE = [
  '/manifest.webmanifest',
  '/icon-192.png',
  '/icon-512.png',
  '/static/touchbar.js',
];

const OFFLINE_HTML = `<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#121620">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Media Stick</title>
<style>
body{margin:0;min-height:100vh;min-height:100svh;box-sizing:border-box;display:flex;align-items:center;justify-content:center;background:#121620;color:#fff;font:16px/1.45 system-ui,-apple-system,sans-serif;text-align:center;padding:calc(24px + env(safe-area-inset-top)) calc(24px + env(safe-area-inset-right)) calc(24px + env(safe-area-inset-bottom)) calc(24px + env(safe-area-inset-left))}
.box{max-width:340px;background:#1F2633;border-radius:24px;padding:28px 22px;box-shadow:0 8px 24px rgba(0,0,0,.35)}
.spin{width:36px;height:36px;margin:0 auto 16px;border-radius:50%;border:3px solid rgba(255,255,255,.15);border-top-color:#fff;animation:s 1s linear infinite}
@keyframes s{to{transform:rotate(360deg)}}
h1{font-size:19px;margin:0 0 8px;font-weight:600}
p{margin:0;color:rgba(255,255,255,.7);font-size:14px}
</style></head><body>
<div class="box"><div class="spin"></div><h1>Ищу приставку…</h1><p>Перезагрузка или переключение Wi-Fi. Страница откроется сама.</p></div>
<script>
setInterval(()=>{fetch('/api/status',{cache:'no-store'}).then(r=>{if(r.ok)location.reload()}).catch(()=>{})},2000);
</script></body></html>`;

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE))
      .catch(() => {})
      .finally(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function isCacheableStatic(url) {
  if (url.origin !== self.location.origin) return false;
  if (url.pathname.startsWith('/static/')) return true;
  return url.pathname === '/manifest.webmanifest' || url.pathname === '/icon-192.png' || url.pathname === '/icon-512.png';
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname === '/ws' || url.pathname.startsWith('/shot.')) {
    return;
  }

  if (isCacheableStatic(url)) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((resp) => {
          if (resp && resp.ok) {
            const copy = resp.clone();
            caches.open(CACHE_NAME).then((c) => c.put(req, copy)).catch(() => {});
          }
          return resp;
        });
      })
    );
    return;
  }

  if (req.mode === 'navigate' || url.pathname === '/') {
    event.respondWith(
      fetch(req).catch(() => new Response(OFFLINE_HTML, {
        status: 503,
        headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' },
      }))
    );
  }
});
