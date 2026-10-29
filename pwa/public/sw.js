const CACHE='dosym-public-v1';
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(['/offline.html','/offline.js','/offline-locales.js','/icons/icon.svg']))));
self.addEventListener('activate',event=>event.waitUntil(self.clients.claim()));
self.addEventListener('message',event=>{if(event.data?.type==='SKIP_WAITING')self.skipWaiting();});
self.addEventListener('fetch',event=>{
 const request=event.request,url=new URL(request.url);
 if(request.method!=='GET'||url.origin!==self.location.origin||url.pathname.startsWith('/api/')||request.headers.has('authorization'))return;
 // Next.js development chunks can reuse URLs between edits; never keep them in the PWA cache on loopback.
 if((url.hostname==='localhost'||url.hostname==='127.0.0.1')&&url.pathname.startsWith('/_next/static/'))return;
 if(request.mode==='navigate'){
  // A static offline shell does not depend on server-rendered HTML hydration.
  event.respondWith(fetch(request).catch(async()=>{const cache=await caches.open(CACHE);return await cache.match('/offline.html');}));return;
 }
 if(url.pathname==='/offline.js'||url.pathname==='/offline-locales.js'||url.pathname==='/offline.html'||['/avatar/','/_next/static/','/fonts/','/icons/'].some(prefix=>url.pathname.startsWith(prefix))){
  event.respondWith(caches.open(CACHE).then(async cache=>{const cached=await cache.match(request);if(cached)return cached;const response=await fetch(request);if(response.ok)await cache.put(request,response.clone());return response;}));
 }
});
