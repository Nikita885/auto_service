/* Service worker веб-приложения. Версия {{ version }}.

   Задача у него скромная: чтобы приложение с главного экрана открывалось
   мгновенно и без сети показывало хотя бы себя, а не белый экран Safari.
   Данные (API) он не кеширует никогда: последние ответы хранят сами
   экраны (`cache` в app/lib.js) и показывают их только с подписью
   «нет сети · данные на 21:40» — молча подсунуть старые цифры воркер
   не должен.

   - `/static/…` — из кеша, в фоне обновляем (stale-while-revalidate): в
     проде в именах хеш, так что новая версия приходит новым адресом;
   - страница `/app/` — сначала сеть, без сети — последняя сохранённая;
   - `/api/`, `/ws/` и всё остальное — мимо воркера. */

const CACHE = "app-{{ version }}";
const SHELL = "/app/";
const ASSETS = [{% for asset in assets %}"{{ asset|escapejs }}"{% if not forloop.last %}, {% endif %}{% endfor %}];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll([SHELL, ...ASSETS]))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  // Старые версии кеша удаляем: иначе они копятся на телефоне с каждой выкаткой.
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;

  if (request.mode === "navigate" && url.pathname.startsWith("/app/")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(SHELL, copy));
          return response;
        })
        .catch(() => caches.match(SHELL))
    );
    return;
  }

  if (url.pathname.startsWith("/static/")) {
    event.respondWith(
      caches.open(CACHE).then((cache) =>
        cache.match(request).then((cached) => {
          const fresh = fetch(request)
            .then((response) => {
              if (response.ok) cache.put(request, response.clone());
              return response;
            })
            .catch(() => cached);
          return cached || fresh;
        })
      )
    );
  }
});
