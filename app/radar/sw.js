/* Service worker do radar de campo.
   Cache-first para os próprios arquivos do app. Em campo não há internet, e o app
   não busca mais nada da rede — o plano vem de um arquivo local escolhido pelo usuário. */
const CACHE = 'penetro3d-radar-v1';
const ARQUIVOS = ['radar_campo.html', 'manifest.json', 'icone.svg'];

self.addEventListener('install', ev => {
  ev.waitUntil(caches.open(CACHE).then(c => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', ev => {
  ev.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener('fetch', ev => {
  if (ev.request.method !== 'GET') return;
  ev.respondWith(
    caches.match(ev.request).then(r => r || fetch(ev.request).then(resp => {
      const copia = resp.clone();
      caches.open(CACHE).then(c => c.put(ev.request, copia)).catch(() => {});
      return resp;
    }).catch(() => caches.match('radar_campo.html')))
  );
});
