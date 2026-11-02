const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const html=fs.readFileSync(path.join(__dirname,'../web/avatar.html'),'utf8');
const start=html.indexOf('function interpolateShortPoseGaps(');
const load=()=>{
  assert.ok(start>=0,'interpolateShortPoseGaps must exist');
  const context={};vm.createContext(context);
  vm.runInContext(html.slice(start,html.indexOf('\nfunction ',start+10)),context);
  return context.interpolateShortPoseGaps;
};
const frame=(x,y)=>[x,y,0.1,.5,.5,.1];
const zero=()=>[0,0,0,0,0,0];

test('short pose gaps are linearly filled between valid detections',()=>{
  const fill=load(),track=[frame(0,0),zero(),zero(),frame(.3,.6)];
  const out=fill(track,4);
  assert.deepEqual(out[1].slice(0,2).map(v=>+v.toFixed(3)),[.1,.2]);
  assert.deepEqual(out[2].slice(0,2).map(v=>+v.toFixed(3)),[.2,.4]);
  assert.equal(out[1][3],.5);
  assert.equal(track[1][0],0,'input must not be mutated');
});

test('gaps longer than the limit and edge gaps stay missing',()=>{
  const fill=load();
  const long=fill([frame(0,0),zero(),zero(),zero(),zero(),zero(),frame(1,1)],3);
  assert.ok(long.slice(1,6).every(f=>f.every(v=>v===0)));
  const edges=fill([zero(),frame(.2,.2),zero()],5);
  assert.ok(edges[0].every(v=>v===0)&&edges[2].every(v=>v===0));
});

test('each landmark is filled independently and null passes through',()=>{
  const fill=load(),a=[1,1,1,0,0,0],b=[0,0,0,2,2,2],c=[1,1,1,0,0,0];
  const out=fill([a,b,c],3);
  assert.deepEqual(out[1].slice(0,3),[1,1,1]);
  assert.deepEqual(out[1].slice(3,6),[2,2,2],'landmark 2 valid in the middle frame is untouched');
  assert.equal(fill(null,3),null);
});
