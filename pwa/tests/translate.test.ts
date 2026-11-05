import {test} from 'node:test';
import assert from 'node:assert/strict';
import {planSigns} from '../lib/translate.ts';

const g=(id:string,label:string,aliases?:string[])=>({id,label,language:'kk-KZ',metadata:{},aliases});
const library=[g('su','Су',['вода']),g('m','М'),g('e','Е'),g('n','Н'),g('k','Қ')];

test('a sentence keeps its order and spells the words that have no sign',()=>{
 const plan=planSigns('мен су',library);
 assert.deepEqual(plan.sequence.map(item=>item.id),['m','e','n','su']);
 assert.deepEqual(plan.spelled,['мен']);
 assert.deepEqual(plan.lost,[]);
});

test('words made only of unknown letters are reported, not dropped silently',()=>{
 const plan=planSigns('xyz су',library);
 assert.deepEqual(plan.sequence.map(item=>item.id),['su']);
 assert.deepEqual(plan.lost,['xyz']);
});

test('a chosen gesture plays alone',()=>{
 assert.deepEqual(planSigns('ignored',library,library[0]).sequence.map(item=>item.id),['su']);
});
