import type { NextRequest } from 'next/server';
export const runtime='nodejs';
export const dynamic='force-dynamic';
async function handle(request:NextRequest, context:{params:Promise<{path:string[]}>}) {
  const { path }=await context.params;
  if (!path.every(p=>/^[a-zA-Z0-9_-]+$/.test(p))) return Response.json({error:'Некорректный путь.'},{status:400});
  const localRequest=path.join('/')==='auth/local'||request.headers.get('authorization')?.startsWith('Bearer local:');
  if(localRequest){
    // No forwarding: Python must see the actual socket peer for local identities.
    return Response.json({error:'Тестовая сессия доступна только напрямую через локальный Python-сервис.'},{status:403});
  }
  if (!['health','auth','me','submissions','moderation','gestures','training','uploads'].includes(path[0])) return new Response(null,{status:404});
  // Video chunks go directly to the upload service, never through Vercel.
  if(['chunks','source','motion'].includes(path.at(-1)||'')) return Response.json({error:'Используйте прямой адрес видеосервиса.'},{status:400});
  const headers=new Headers();
  for(const name of ['authorization','content-type','range','origin']) { const value=request.headers.get(name);if(value)headers.set(name,value); }
  try {
    const body=['GET','HEAD'].includes(request.method)?undefined:await request.text();
    if(body && body.length>32768) return Response.json({error:'Слишком большой запрос.'},{status:413});
    const target=new URL(path.join('/'),(process.env.BACKEND_URL||'http://127.0.0.1:8765')+'/');
    const response=await fetch(target,{method:request.method,headers,body,cache:'no-store',signal:AbortSignal.timeout(120000)});
    const outgoing=new Headers({'Cache-Control':'no-store'});
    for(const name of ['content-type','content-length','content-range','accept-ranges']){const v=response.headers.get(name);if(v)outgoing.set(name,v);}
    return new Response(response.body,{status:response.status,headers:outgoing});
  } catch { return Response.json({error:'Сервис обработки недоступен. Запустите Python-сервис и повторите.'},{status:503,headers:{'Cache-Control':'no-store'}}); }
}
export {handle as GET,handle as POST,handle as PUT};
