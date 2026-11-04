import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {frameFromHands,gestureFeatures,classify,parseModel} from '../lib/camera-classifier.ts';

const fixtures=JSON.parse(readFileSync(new URL('./fixtures/camera-features.json',import.meta.url),'utf8')) as {aspect:number;frames:number[][][][];expected:number[]}[];

test('browser features equal the Python training features (one hand, two hands, hands coming and going)',()=>{
 for(const sample of fixtures){
  const frames=sample.frames.map(hands=>frameFromHands(hands.map(hand=>hand.map(([x,y,z])=>({x,y,z}))),sample.aspect));
  const got=gestureFeatures(frames,12);
  assert.equal(got.length,sample.expected.length);
  let worst=0;
  for(let i=0;i<got.length;i++)worst=Math.max(worst,Math.abs(got[i]-sample.expected[i])/(1+Math.abs(sample.expected[i])));
  assert.ok(worst<2e-3,`largest relative difference ${worst}`);
 }
});

function packModel(hidden:number,classes:string[],features:number){
 const sizes=[features*hidden,hidden,hidden*classes.length,classes.length];
 const bits=new Uint16Array(sizes.reduce((a,b)=>a+b,0));
 // half-float 1.0 = 0x3c00, 0 = 0
 const one=0x3c00,w1=bits.subarray(0,sizes[0]),w2=bits.subarray(sizes[0]+sizes[1],sizes[0]+sizes[1]+sizes[2]);
 for(let i=0;i<features;i++)w1[i*hidden+(i%hidden)]=one; // input i feeds hidden unit i % hidden
 for(let j=0;j<hidden;j++)w2[j*classes.length+(j%classes.length)]=one;
 return {meta:{schema:1,steps:12,features,hidden,classes,mean:Array(features).fill(0),scale:Array(features).fill(1),threshold:.35},buffer:bits.buffer};
}

test('the exported model format round-trips and the softmax output is a probability distribution',()=>{
 const features=fixtures[0].expected.length,classes=['Бір','Екі','Үш'];
 const {meta,buffer}=packModel(6,classes,features);
 const model=parseModel(meta,buffer);
 const result=classify(model,Float32Array.from(fixtures[0].expected),3);
 assert.equal(result.length,3);
 assert.ok(Math.abs(result.reduce((sum,item)=>sum+item.probability,0)-1)<1e-5);
 assert.ok(result[0].probability>=result[1].probability);
 assert.throws(()=>parseModel({...meta,classes:['x']},buffer));
 assert.throws(()=>parseModel(meta,buffer.slice(0,buffer.byteLength-2)));
});

test('the shipped model gives the same top words as the Python forward pass',()=>{
 const meta=JSON.parse(readFileSync(new URL('../public/camera/model.json',import.meta.url),'utf8'));
 const bytes=readFileSync(new URL('../public/camera/model.bin',import.meta.url));
 const model=parseModel(meta,bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength));
 const expected=JSON.parse(readFileSync(new URL('./fixtures/camera-model-expected.json',import.meta.url),'utf8')) as {top:{label:string;p:number}[]}[];
 fixtures.forEach((sample,i)=>{
  const got=classify(model,Float32Array.from(sample.expected),3);
  assert.equal(got[0].label,expected[i].top[0].label);
  assert.ok(Math.abs(got[0].probability-expected[i].top[0].p)<.02,`probability ${got[0].probability} vs ${expected[i].top[0].p}`);
 });
 assert.ok(model.classes.length>=500);
});
