import test from 'node:test';
import assert from 'node:assert/strict';
import { GET } from '../app/api/[...path]/route.ts';
import type { NextRequest } from 'next/server';

test('hosted Supabase sign-in works without a Python backend and never grants moderation', async () => {
 const originalEnv={...process.env}, originalFetch=globalThis.fetch;
 delete process.env.BACKEND_URL;
 process.env.NEXT_PUBLIC_SUPABASE_URL='https://auth.example.test';
 process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY='public-test-key';
 const request=(path:string,headers:HeadersInit={})=>GET(new Request('https://app.example.test/api/'+path,{headers}) as NextRequest,{params:Promise.resolve({path:path.split('/')})});
 try {
  globalThis.fetch=async(input,options)=>{
   assert.equal(String(input),'https://auth.example.test/auth/v1/user');
   const headers=new Headers(options?.headers);
   assert.equal(headers.get('apikey'),'public-test-key');
   assert.equal(headers.get('authorization'),'Bearer valid-session');
   return Response.json({id:'verified-user',email:'user@example.test',user_metadata:{full_name:'Participant',role:'moderator'},app_metadata:{role:'moderator'}});
  };
  const config=await request('auth/config');
  assert.equal(config.status,200);
  assert.equal((await config.json()).google_configured,true);
  assert.equal((await request('me')).status,401);
  const identity=await request('me',{Authorization:'Bearer valid-session'});
  assert.deepEqual(await identity.json(),{id:'verified-user',email:'user@example.test',name:'Participant',role:'user'});
  globalThis.fetch=async()=>Response.json({error:'expired'},{status:401});
  assert.equal((await request('me',{Authorization:'Bearer expired'})).status,401);
  assert.equal((await request('me',{Authorization:'Bearer local:forged'})).status,403);
 } finally {process.env=originalEnv;globalThis.fetch=originalFetch;}
});
