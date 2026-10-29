import test from 'node:test';
import assert from 'node:assert/strict';
import { completeSupabaseCallback } from '../lib/auth-callback.ts';

test('an automatically established PKCE session never consumes the one-time code twice',async()=>{
 let exchanges=0;
 await completeSupabaseCallback({
  getSession:async()=>({data:{session:{access_token:'verified-session'}},error:null}),
  exchangeCodeForSession:async()=>{exchanges++;throw new Error('code already consumed');},
 },'already-consumed');
 assert.equal(exchanges,0);
});

test('callback exchanges a pending code once and propagates a rejected exchange',async()=>{
 let exchanges=0;
 const auth={getSession:async()=>({data:{session:null},error:null}),exchangeCodeForSession:async(code:string)=>{assert.equal(code,'pending-code');exchanges++;return {error:null};}};
 await completeSupabaseCallback(auth,'pending-code');
 assert.equal(exchanges,1);
 await assert.rejects(completeSupabaseCallback({...auth,exchangeCodeForSession:async()=>({error:new Error('expired')})},'expired'),/expired/);
 await assert.rejects(completeSupabaseCallback(auth,null),/session/i);
});
