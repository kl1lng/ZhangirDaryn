import {test} from 'node:test';
import assert from 'node:assert/strict';
import {KAZAKH_LATIN,matchGesture,searchGesture,resolvePhrase,uniqueGestures} from '../lib/gesture-search.ts';
const g=(label:string)=>({id:label,label,language:'kk-KZ',metadata:{}});
test('current and future labels match both Unicode Latin and everyday input',()=>{
 for(const [label,inputs] of [['Сәлем',['salem','SÄLEM','sa\u0308lem']],['Өрік',['örik','orik']],['Үміт',['ümit','umit']],['Ұлан',['ūlan','ulan']],['Ғарыш',['ğaryş','garys','gharysh']],['Жаңа',['jaña','zhanga','jaŋa']],['Қалай',['qalai','qalay']]] as const){
  for(const input of inputs)assert.equal(matchGesture(input,[g(label)]).matches[0]?.label,label,input);
 }
 assert.equal(matchGesture('BİLİM',[g('Білім')]).matches[0]?.label,'Білім');
});
test('letters work without a per-word alias list',()=>{
 for(const [label,input] of [['Ә','ä'],['Ө','ö'],['Ү','ü'],['Ұ','ū'],['Ғ','ğ'],['Қ','q'],['Ң','ñ'],['Ш','ş'],['І','ı']]){
  assert.equal(matchGesture(input,[g(label)]).matches[0]?.label,label);
 }
 const letters=Object.keys(KAZAKH_LATIN).map(g);
 assert.equal(letters.length,42);
 for(const letter of letters)assert.ok(matchGesture(KAZAKH_LATIN[letter.label],letters).matches.some(row=>row.id===letter.id),letter.label);
});
test('exact spelling wins and lossy ASCII collisions need a choice',()=>{
 const labels=[g('Ар'),g('Әр')];
 assert.equal(matchGesture('Әр',labels).matches[0].label,'Әр');
 assert.equal(matchGesture('är',labels).matches[0].label,'Әр');
 assert.equal(matchGesture('ar',labels).ambiguous,true);
 assert.equal(matchGesture('ar',labels).matches.length,2);
 assert.equal(matchGesture('Ә', [g('А')]).matches.length,0);
});
test('dictionary and suggestions show one sample for duplicate phrase labels',()=>{
 const rows=[{...g('Сәлем'),id:'first'},{...g('Сәлем'),id:'second'},g('Сәлеметсіз_бе'),g('Сәлеметсіз бе')];
 assert.deepEqual(uniqueGestures(rows).map(row=>row.id),['first','Сәлеметсіз_бе']);
});
test('long phrases win, missing text stays missing and dictionary searches Latin',()=>{
 const labels=[g('Қайырлы күн'),g('Сәлем')];
 const result=resolvePhrase('Qaiyrly kün, salem! unknown',labels);
 assert.deepEqual(result.matches.map(x=>x.label),['Қайырлы күн','Сәлем']);
 assert.deepEqual(result.missing,['unknown']);
 assert.ok(searchGesture('Сәлем','sal'));
 assert.ok(searchGesture('Өрік','örik'));
 assert.equal(matchGesture('hello',labels).matches.length,0);
});
