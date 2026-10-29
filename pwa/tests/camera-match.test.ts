import test from 'node:test';
import assert from 'node:assert/strict';
import {handFeatures,prepareReference,rankExamples} from '../lib/camera-match.ts';

const hand=(offset=0)=>Array.from({length:21},(_,i)=>({x:.3+(i%5)*.02+offset,y:.5-Math.floor(i/5)*.03,z:i*.001}));
const frame=(offset=0)=>handFeatures([hand(offset)],[[{categoryName:'Right',score:1}]]);
test('camera handedness matches unmirrored extraction and missing hands stay empty',()=>{
 const row=frame();assert.ok(row.slice(0,63).some(x=>x!==0));assert.ok(row.slice(63).every(x=>x===0));
 assert.deepEqual(handFeatures([],[]),Array(126).fill(0));
});
test('temporal matching ranks actual shape and motion without mutating references',()=>{
 const sequence=Array.from({length:24},(_,i)=>frame(i*.003));
 const different=sequence.map(row=>row.map((x,i)=>i<63?x+(i%3===1?.2:0):x));
 const refs=[prepareReference({id:'a',label:'А',sequence}),prepareReference({id:'b',label:'Б',sequence:different}),prepareReference({id:'a2',label:'А',sequence})];
 const before=JSON.stringify(refs);
 const matches=rankExamples(sequence,refs);
 assert.equal(matches[0]?.label,'А');assert.equal(matches.filter(x=>x.label==='А').length,1);
 assert.equal(JSON.stringify(refs),before);
 assert.deepEqual(rankExamples(Array.from({length:24},()=>Array(126).fill(0)),refs),[]);
 assert.deepEqual(rankExamples(sequence.slice(0,3),refs),[]);
 assert.deepEqual(rankExamples(sequence.map(row=>row.map((x,i)=>i%3===0&&i<63?x+5:x)),refs),[]);
});
