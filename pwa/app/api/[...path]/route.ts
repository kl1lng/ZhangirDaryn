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
  const library=process.env.NEXT_PUBLIC_LIBRARY_URL;
  if(!process.env.BACKEND_URL && library && request.method==='GET' && path.join('/')==='gestures'){
    try{
      const response=await fetch(library.replace(/\/$/,'')+'/catalog.json',{cache:'no-store',signal:AbortSignal.timeout(10000)});
      if(!response.ok)throw new Error('Library unavailable');
      const catalog=await response.json();
      if(!Array.isArray(catalog)||catalog.some(row=>!row||typeof row.id!=='string'||!/^[a-zA-Z0-9_-]+$/.test(row.id)||typeof row.label!=='string'||typeof row.version!=='string'))throw new Error('Invalid catalog');
      return Response.json(catalog,{headers:{'Cache-Control':'no-store'}});
    }catch{return Response.json({error:'Библиотека временно недоступна.'},{status:503,headers:{'Cache-Control':'no-store'}});}
  }
  // A frontend-only deployment can authenticate before the ML service is hosted.
  // Supabase app_metadata is server-controlled; never trust user_metadata for roles.
  const supabaseUrl=process.env.NEXT_PUBLIC_SUPABASE_URL;
  const supabaseKey=process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if(!process.env.BACKEND_URL && supabaseUrl && supabaseKey && request.method==='GET'){
    const endpoint=path.join('/');
    const privateHeaders={'Cache-Control':'no-store'};
    if(endpoint==='auth/config')return Response.json({auth_provider:'supabase',local_auth:false,google_configured:true,storage:'unavailable'},{headers:privateHeaders});
    if(endpoint==='me'){
      const authorization=request.headers.get('authorization');
      if(!authorization?.startsWith('Bearer '))return Response.json({error:'Требуется вход.'},{status:401,headers:privateHeaders});
      try{
        const response=await fetch(new URL('/auth/v1/user',supabaseUrl),{headers:{apikey:supabaseKey,authorization},cache:'no-store',signal:AbortSignal.timeout(10000)});
        if(!response.ok)return Response.json({error:'Сессия не подтверждена.'},{status:response.status===401||response.status===403?401:503,headers:privateHeaders});
        const identity=await response.json();
        if(!identity.id)return Response.json({error:'Сессия не подтверждена.'},{status:401,headers:privateHeaders});
        const googleVerified=Boolean(identity.email_confirmed_at)&&Array.isArray(identity.identities)&&identity.identities.some((item:{provider?:string})=>item.provider==='google');
        const role=googleVerified&&identity.app_metadata?.dosym_role==='moderator'?'moderator':'user';
        return Response.json({id:identity.id,email:identity.email||'',name:identity.user_metadata?.full_name||identity.user_metadata?.name||'',role},{headers:privateHeaders});
      }catch{return Response.json({error:'Сервис входа недоступен.'},{status:503,headers:privateHeaders});}
    }
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
