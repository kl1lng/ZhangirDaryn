const test=require('node:test');
const assert=require('node:assert/strict');
const THREE=require('three');
const fs=require('node:fs');
const vm=require('node:vm');
const api=()=>import('../web/rig-motion.mjs');

function fixture(){
  const root=new THREE.Bone(),child=new THREE.Bone();root.name='arm';child.name='hand';
  child.position.set(0,-.3,0);root.add(child);root.updateMatrixWorld(true);
  return [root,child];
}

test('prepared motion seeks identically after arbitrary playback history without calling IK',async()=>{
  const {bakeRigMotion,applyPreparedFrame}=await api(),bones=fixture();let solves=0;
  const data=bakeRigMotion({bones,frameCount:5,fps:25,solveFrame:i=>{
    solves++;bones[0].quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),i*.1);
  }});
  const source=Array.from(data.rotations);
  for(const position of [2.5,0,4,1,2.5]){
    applyPreparedFrame(data,bones,position);bones[0].updateMatrixWorld(true);
    assert.ok(Math.abs(bones[1].getWorldPosition(new THREE.Vector3()).length()-.3)<1e-6);
  }
  assert.ok(Math.abs(bones[0].quaternion.angleTo(new THREE.Quaternion())-.25)<1e-6);
  assert.equal(solves,5);assert.deepEqual(Array.from(data.rotations),source);
});

test('chunked preparation yields to the event loop and preserves the synchronous motion data',async()=>{
  const {bakeRigMotion,bakeRigMotionAsync}=await api(),syncBones=fixture(),asyncBones=fixture(),order=[],chunks=[];
  const source={frameCount:5,fps:25,groups:[[0,1]],tracked:i=>[i!==3],
    solveFrame:(bones,tag)=>(frame=>{order.push(`${tag}:${frame}`);bones[0].quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),frame*.08);})};
  const sync=bakeRigMotion({bones:syncBones,frameCount:source.frameCount,fps:source.fps,groups:source.groups,tracked:source.tracked,solveFrame:source.solveFrame(syncBones,'sync')});
  const chunked=await bakeRigMotionAsync({bones:asyncBones,frameCount:source.frameCount,fps:source.fps,groups:source.groups,tracked:source.tracked,
    solveFrame:source.solveFrame(asyncBones,'async'),chunkSize:2,onChunk:chunk=>chunks.push(chunk),yieldControl:async()=>{order.push('yield');await Promise.resolve();}});
  assert.deepEqual(Array.from(chunked.rotations),Array.from(sync.rotations));
  assert.deepEqual(chunked.quality,sync.quality);
  assert.deepEqual(order.filter(item=>item==='yield'),['yield','yield']);
  assert.deepEqual(order.filter(item=>item.startsWith('async:')),['async:0','async:1','async:2','async:3','async:4']);
  assert.deepEqual(chunks.map(({fromFrame,toFrame})=>[fromFrame,toFrame]),[[0,1],[2,3]]);
});

test('chunked preparation stops stale motion after a request is cancelled',async()=>{
  const {bakeRigMotionAsync}=await api(),bones=fixture(),controller=new AbortController(),frames=[];
  await assert.rejects(bakeRigMotionAsync({bones,frameCount:8,fps:25,chunkSize:2,signal:controller.signal,
    solveFrame:frame=>frames.push(frame),yieldControl:async()=>{controller.abort();}}),error=>error.name==='AbortError');
  assert.deepEqual(frames,[0,1]);
});

test('pausing while an avatar clip is being prepared stays paused after preparation finishes',async()=>{
  const html=fs.readFileSync(require('node:path').join(__dirname,'../web/avatar.html'),'utf8');
  const start=html.indexOf('async function startPreparedPlayback('),end=html.indexOf('async function prepareRigPlayback(',start);
  const elements=new Map(['#motion-editor','#caption','#preparation-status','#empty','#motion-progress'].map(id=>[id,{}]));
  let generation=0,scheduled=0;
  const context={
    playbackGeneration:0,playTimer:null,activeSequence:[Array(162).fill(.1)],activeFps:24,activeLabel:'сәлем',activeLanguage:'kk-KZ',
    activeBodyPose:[Array(18).fill(.2)],activeBodyPoseWorld:null,activeImageAspectRatio:1,voiceMissing:[],voiceQueue:[],
    humanRigBones:[{}],humanLoadFailed:false,preparedMotion:null,preparedRecord:null,preparedKey:null,preparing:false,
    stopMotion(){this.playbackGeneration=++generation;},
    document:{querySelector:id=>elements.get(id)||{}},
    stabilizeHandTrack:sequence=>sequence,interpolateShortHandGaps:sequence=>sequence,stabilizeMotionTrack:track=>track,
    applyNeutralPose(){},calibrateMotion(){},prepareRigPlayback:async()=>{context.paused=true;},
    findOpeningRestEnd:()=>0,findClosingRestStart:()=>null,normalizeImageAspectRatio:value=>value,
    handL:{group:{visible:true},tracked:true,pose:{}},handR:{group:{visible:true},tracked:true,pose:{}},
    lastHandAssignment:null,previousArmPole:[null,null],previousWristTwist:[null,null],frameIndex:0,playbackElapsed:0,
    requestAnimationFrame:()=>++scheduled,advanceMotion(){},paused:false,renderFrame(){},
  };
  vm.createContext(context);vm.runInContext(html.slice(start,end),context);
  await context.startPreparedPlayback({signal:new AbortController().signal});
  assert.equal(context.paused,true);
  assert.equal(context.playTimer,null,'the preparation must not restart animation after a pause request');
});

test('missing arm poses hold briefly then blend to neutral instead of snapping to bind pose',async()=>{
  const {bakeRigMotion,applyPreparedFrame}=await api(),bones=fixture();
  const data=bakeRigMotion({bones,frameCount:12,fps:25,groups:[[0,1]],
    tracked:i=>[i===0],solveFrame:i=>bones[0].quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),i===0?.6:2)});
  applyPreparedFrame(data,bones,2);assert.ok(Math.abs(bones[0].quaternion.angleTo(new THREE.Quaternion())-.6)<1e-6);
  applyPreparedFrame(data,bones,7);const angle=bones[0].quaternion.angleTo(new THREE.Quaternion());
  assert.ok(angle>0&&angle<.6);
  applyPreparedFrame(data,bones,11);assert.ok(bones[0].quaternion.angleTo(new THREE.Quaternion())<1e-6);
  assert.equal(data.quality.missingFrames[0],11);
});

test('preparation limits a single-frame elbow flip and reports that it changed motion',async()=>{
  const {bakeRigMotion,applyPreparedFrame}=await api(),bones=fixture();
  const data=bakeRigMotion({bones,frameCount:3,fps:30,solveFrame:i=>bones[0].quaternion.setFromAxisAngle(new THREE.Vector3(0,0,1),i===1?Math.PI:0)});
  applyPreparedFrame(data,bones,1);
  assert.ok(bones[0].quaternion.angleTo(new THREE.Quaternion())<1);
  assert.ok(data.quality.limitedRotations>0);
});

test('cache validation rejects a different rig, broken quaternion or stale version',async()=>{
  const {bakeRigMotion,isPreparedMotion}=await api(),bones=fixture();
  const data=bakeRigMotion({bones,frameCount:1,fps:30,solveFrame:()=>{}});
  assert.equal(isPreparedMotion(data,bones,1,30),true);
  assert.equal(isPreparedMotion({...data,version:'old'},bones,1,30),false);
  assert.equal(isPreparedMotion(data,bones.slice(1),1,30),false);
  assert.equal(isPreparedMotion(data,bones,2,30),false);
  assert.equal(isPreparedMotion({...data,quality:null},bones,1,30),false);
  data.rotations[0]=NaN;assert.equal(isPreparedMotion(data,bones,1,30),false);
});

test('cache key changes for changed source, calibration, skeleton or pipeline',async()=>{
  const {motionFingerprint}=await api();const source={sequence:[[.1,.2,.3]],fps:30,aspect:1,rig:'A'};
  const a=await motionFingerprint(source);
  assert.equal(await motionFingerprint(source),a);
  for(const changed of [{fps:24},{aspect:1.5},{rig:'B'},{sequence:[[.1,.2,.4]]}])
    assert.notEqual(await motionFingerprint({...source,...changed}),a);
});

test('range corrections fade at boundaries and never modify other arm or frames',async()=>{
  const {correctionAt}=await api();
  const edits=[{from:10,to:30,side:0,depth:.1,roll:.4,contact:true}];
  assert.equal(correctionAt(edits,0,0,30).depth,0);
  assert.equal(correctionAt(edits,20,1,30).depth,0);
  assert.equal(correctionAt(edits,20,0,30).depth,.1);
  assert.equal(correctionAt(edits,20,0,30).contact,true);
  assert.ok(correctionAt(edits,10,0,30).depth>0&&correctionAt(edits,10,0,30).depth<.1);
  assert.equal(correctionAt(edits,31,0,30).contact,false);
});

test('loading an empty clip clears old prepared animation and disables export/review',async()=>{
  const html=fs.readFileSync(require('node:path').join(__dirname,'../web/avatar.html'),'utf8');
  const editor={disabled:false},caption={textContent:''};let stopped=0;
  const context={activeSequence:[],preparedMotion:{old:true},preparedRecord:{old:true},preparedKey:'old',
    preparing:false,playbackGeneration:1,stopMotion:()=>{stopped++},
    document:{querySelector:s=>s==='#motion-editor'?editor:caption}};
  vm.createContext(context);
  vm.runInContext(html.slice(html.indexOf('async function startPreparedPlayback('),html.indexOf('async function prepareRigPlayback(')),context);
  await context.startPreparedPlayback({});
  assert.equal(stopped,1);assert.equal(context.preparedMotion,null);assert.equal(context.preparedRecord,null);
  assert.equal(context.preparedKey,null);assert.equal(editor.disabled,true);assert.equal(context.preparing,false);
});

test('unavailable browser storage reports an error rather than a false persistence success',async()=>{
  const {motionStore}=await api();await assert.rejects(motionStore('get','test'),/хранилище/);
});

test('replay retains edited animation in memory when durable storage is unavailable',async()=>{
  const {createMotionRepository}=await api();
  const repository=createMotionRepository(async()=>{throw new Error('storage disabled')});
  const record={edits:[{from:2,to:8,depth:.04}],reviewed:false};
  const saved=await repository.put('clip-A',record);assert.equal(saved,false);
  const loaded=await repository.get('clip-A');assert.deepEqual(loaded.record,record);assert.equal(loaded.persisted,false);
  assert.equal((await repository.get('clip-B')).record,null);
});
