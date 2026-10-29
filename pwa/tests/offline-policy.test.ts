import {test} from 'node:test';
import assert from 'node:assert/strict';
import {staleOfflineIds} from '../lib/offline-policy.ts';
test('reconnection evicts revoked and changed motions, preserving matching versions',()=>{
 assert.deepEqual(staleOfflineIds([{id:'a',version:'one'},{id:'b',version:'old'},{id:'c',version:'gone'}],[{id:'a',version:'one'},{id:'b',version:'new'}]),['b','c']);
});
test('invalid catalog never silently erases saved data',()=>{
 assert.throws(()=>staleOfflineIds([{id:'a',version:'one'}],[{id:'a'}] as {id:string;version:string}[]));
});
