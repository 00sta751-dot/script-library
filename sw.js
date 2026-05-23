// v3 2026-05-23 自殺版 — unregister 自己 + 清所有 cache + 強制 reload
// 解決 v1/v2 service worker 鎖死舊 cache 問題
// 用戶 1 次訪問後永遠不再受 sw cache 影響

self.addEventListener('install', function(e) {
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(names.map(function(n) { return caches.delete(n); }));
    }).then(function() {
      return self.registration.unregister();
    }).then(function() {
      return self.clients.matchAll({ type: 'window' });
    }).then(function(clients) {
      clients.forEach(function(c) {
        if (c.navigate) c.navigate(c.url);
      });
    })
  );
});

self.addEventListener('fetch', function(e) {
  // 不攔截 — 直接走網路
  return;
});
