const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const test=require('node:test');
const THREE=require('three');
const html=fs.readFileSync(path.join(__dirname,'../web/avatar.html'),'utf8');
const functions=(from,to)=>html.slice(html.indexOf(from),html.indexOf(to,html.indexOf(from)));

function makeRig(){
  // Read the real GLB node hierarchy. Meshes/textures are unnecessary for
  // verifying the same parent transforms and bind offsets used in the browser.
  const glb=fs.readFileSync(path.join(__dirname,'../web/models/rocketbox-male-adult-02.glb'));
  const document=JSON.parse(glb.subarray(20,20+glb.readUInt32LE(12)).toString());
  const nodes=document.nodes.map(node=>{
    const bone=new THREE.Bone();bone.name=(node.name||'').replaceAll(' ','_');
    if(node.matrix)new THREE.Matrix4().fromArray(node.matrix).decompose(bone.position,bone.quaternion,bone.scale);
    else{if(node.translation)bone.position.fromArray(node.translation);if(node.rotation)bone.quaternion.fromArray(node.rotation);if(node.scale)bone.scale.fromArray(node.scale)}
    return bone;
  });
  document.nodes.forEach((node,i)=>(node.children||[]).forEach(child=>nodes[i].add(nodes[child])));
  const avatar=new THREE.Group();document.scenes[document.scene||0].nodes.forEach(i=>avatar.add(nodes[i]));
  const find=name=>nodes.find(node=>node.name===name),pos=bone=>bone.getWorldPosition(new THREE.Vector3());
  avatar.updateMatrixWorld(true);
  const head=find('Bip01_Head'),feet=['L','R'].map(side=>find(`Bip01_${side}_Foot`));
  avatar.scale.setScalar(1.75/(pos(head).y-(pos(feet[0]).y+pos(feet[1]).y)/2));avatar.updateMatrixWorld(true);
  avatar.position.add(new THREE.Vector3(-pos(head).x,.58-pos(head).y,-.18-pos(head).z));avatar.updateMatrixWorld(true);
  const bones=['L','R'].flatMap(side=>['UpperArm','Forearm','Hand'].map(part=>find(`Bip01_${side}_${part}`)));
  const rest=bones.map(bone=>({position:bone.position.clone(),quaternion:bone.quaternion.clone()}));
  const fingers=['L','R'].map(side=>Array.from({length:5},(_,finger)=>{
    const chain=['','1','2'].map(end=>find(`Bip01_${side}_Finger${finger}${end}`));
    return{bones:chain,rest:chain.map(bone=>({position:bone.position.clone(),quaternion:bone.quaternion.clone()}))};
  }));
  const context={THREE,humanAvatar:avatar,humanRigBones:bones,humanRigRest:rest,humanRigFingers:fingers,
    previousArmPole:[null,null],previousWristTwist:[null,null],handL:{group:{}},handR:{group:{}},FINGERS:[[1,2,3,4],[5,6,7,8],[9,10,11,12],[13,14,15,16],[17,18,19,20]]};
  vm.createContext(context);
  vm.runInContext(functions('function solveRigArm(','function palmBasis(')+functions('function palmBasis(','const boneColors='),context);
  context.calibrateFingerJoints();
  return{context,avatar,bones,rest,fingers,pos};
}

test('real Rocketbox IK reaches valid targets and preserves bone lengths for both arms',()=>{
  const {context,avatar,bones,rest,pos}=makeRig();
  for(const offset of [0,3]){
    const shoulder=pos(bones[offset]),l1=shoulder.distanceTo(pos(bones[offset+1])),l2=pos(bones[offset+1]).distanceTo(pos(bones[offset+2]));
    for(const targetDelta of [[0,-.4,.25],[.1,-.12,.4],[-.2,.1,.2],[0,-2,1],[0,-.01,0]]){
      bones.forEach((bone,i)=>{bone.position.copy(rest[i].position);bone.quaternion.copy(rest[i].quaternion)});avatar.updateMatrixWorld(true);
      const target=shoulder.clone().add(new THREE.Vector3(...targetDelta));
      context.solveRigArm(offset,offset+1,offset+2,shoulder.clone().add(new THREE.Vector3(offset===0?.3:-.3,-.2,.1)),target);
      assert.ok(Math.abs(pos(bones[offset]).distanceTo(pos(bones[offset+1]))-l1)<1e-6);
      assert.ok(Math.abs(pos(bones[offset+1]).distanceTo(pos(bones[offset+2]))-l2)<1e-6);
      const reach=shoulder.distanceTo(target),minimum=Math.sqrt(l1*l1+l2*l2+2*l1*l2*Math.cos(155*Math.PI/180));
      if(reach>minimum&&reach<l1+l2-.002)assert.ok(pos(bones[offset+2]).distanceTo(target)<1e-5,'reachable wrist target must match the actual hand bone');
      bones.forEach((bone,i)=>{assert.ok(bone.position.distanceTo(rest[i].position)<1e-9);assert.ok(Math.abs(bone.quaternion.length()-1)<1e-6)});
    }
  }
});

function measuredHand(rig,side,bend=.7){
  const {bones,fingers,pos}=rig,hand=bones[side===0?2:5],origin=pos(hand),points=Array.from({length:21},()=>new THREE.Vector3());
  const chains=fingers[side],across=chains[4].rest[0].position.clone().sub(chains[1].rest[0].position),long=chains[2].rest[0].position.clone();
  const normal=across.cross(long).normalize().applyQuaternion(hand.getWorldQuaternion(new THREE.Quaternion()));
  chains.forEach((chain,finger)=>{
    const ids=rig.context.FINGERS[finger];points[ids[0]]=pos(chain.bones[0]).sub(origin);
    let direction=pos(chain.bones[1]).sub(pos(chain.bones[0])).normalize();
    for(let segment=0;segment<3;segment++){
      if(segment&&finger){const axis=direction.clone().cross(normal).normalize();direction.applyAxisAngle(axis,(segment===1?bend:bend*.6)*chain.hinges[segment].flexSign)}
      const length=segment<2?chain.rest[segment+1].position.length():chain.rest[2].position.length()*.7;
      points[ids[segment+1]]=points[ids[segment]].clone().addScaledVector(direction,length*rig.avatar.scale.x);
    }
  });
  return{points};
}

test('wrist cannot fold backwards under an inverted palm detection',()=>{
  for(const side of [0,1]){
    const rig=makeRig(),pose=measuredHand(rig,side),index=side===0?2:5;
    const hand=rig.bones[index],rest=rig.rest[index].quaternion;
    const axis=hand.position.clone().normalize();
    const across=new THREE.Vector3(1,0,0).cross(axis).normalize()
      .applyQuaternion(hand.getWorldQuaternion(new THREE.Quaternion()));
    pose.points.forEach(point=>point.applyAxisAngle(across,2.6));
    rig.context.poseNativeHand(side,pose);
    // Compare the actual forearm and palm longitudinal axes; axial twist
    // cannot hide an impossible backwards wrist bend.
    const before=axis.clone().applyQuaternion(rest);
    const after=axis.clone().applyQuaternion(hand.quaternion);
    assert.ok(before.angleTo(after)<1.23,'wrist flexion must stay below 70 degrees');
    rig.fingers[side].slice(1).forEach(chain=>{
      const directions=chain.bones.slice(0,2).map((bone,i)=>chain.rest[i+1].position.clone()
        .normalize().applyQuaternion(bone.getWorldQuaternion(new THREE.Quaternion())));
      assert.ok(Math.abs(directions[0].angleTo(directions[1])-.7)<.025,
        'correcting the wrist must preserve the measured finger flexion');
    });
  }
});

test('IK moves a wrist target out of the chest without stretching either arm',()=>{
  for(const offset of [0,3]){
    const {context,bones,pos}=makeRig(),shoulder=pos(bones[offset]);
    const target=new THREE.Vector3(0,shoulder.y-.24,shoulder.z);
    const l1=shoulder.distanceTo(pos(bones[offset+1])),l2=pos(bones[offset+1]).distanceTo(pos(bones[offset+2]));
    context.solveRigArm(offset,offset+1,offset+2,shoulder.clone().add(new THREE.Vector3(0,-.2,.1)),target);
    assert.ok(pos(bones[offset+2]).z>shoulder.z+.15,'wrist must be in front of the chest');
    assert.ok(Math.abs(shoulder.distanceTo(pos(bones[offset+1]))-l1)<1e-6);
    assert.ok(Math.abs(pos(bones[offset+1]).distanceTo(pos(bones[offset+2]))-l2)<1e-6);
  }
});

test('local palm correction rotates the whole measured hand without counter-rotating fingers',()=>{
  for(const side of [0,1]){
    const a=makeRig(),b=makeRig(),handIndex=side===0?2:5;
    a.context.poseNativeHand(side,measuredHand(a,side),0);
    b.context.poseNativeHand(side,measuredHand(b,side),.6);
    const correction=b.bones[handIndex].getWorldQuaternion(new THREE.Quaternion())
      .multiply(a.bones[handIndex].getWorldQuaternion(new THREE.Quaternion()).invert());
    assert.ok(correction.angleTo(new THREE.Quaternion())>.3);
    for(let finger=0;finger<5;finger++){
      const direction=rig=>rig.fingers[side][finger].rest[1].position.clone().normalize()
        .applyQuaternion(rig.fingers[side][finger].bones[0].getWorldQuaternion(new THREE.Quaternion()));
      assert.ok(direction(a).applyQuaternion(correction).distanceTo(direction(b))<1e-5,
        'finger shape must rotate with the palm correction');
    }
  }
});

test('real Rocketbox finger hinges reproduce flexion without sideways twist or length changes',()=>{
  for(const side of [0,1]){
    const rig=makeRig(),pose=measuredHand(rig,side),hand=rig.bones[side===0?2:5];
    const before=hand.getWorldQuaternion(new THREE.Quaternion());
    rig.context.poseNativeHand(side,pose);
    const palmError=before.angleTo(hand.getWorldQuaternion(new THREE.Quaternion()));
    assert.ok(palmError<.001,`the measured palm basis keeps its world orientation: side ${side}, error ${palmError}`);
    rig.fingers[side].slice(1).forEach(chain=>{
      const directions=chain.bones.map((bone,i)=>{
        const local=i<2?chain.rest[i+1].position.clone():chain.rest[2].position.clone();
        return local.normalize().applyQuaternion(bone.getWorldQuaternion(new THREE.Quaternion()));
      });
      assert.ok(Math.abs(directions[0].angleTo(directions[1])-.7)<.025,'PIP follows the measured bend');
      assert.ok(Math.abs(directions[1].angleTo(directions[2])-.42)<.025,'DIP follows the measured bend');
      chain.bones.forEach((bone,i)=>{assert.ok(bone.position.distanceTo(chain.rest[i].position)<1e-9);assert.ok(Math.abs(bone.quaternion.length()-1)<1e-6)});
    });
  }
});

test('recorded motion smoothing reduces stationary jitter, keeps gaps and leaves raw data untouched',()=>{
  const context={};vm.createContext(context);
  vm.runInContext(functions('function sampleMotionTrack(','function applyFacialMotion('),context);
  const raw=Array.from({length:80},(_,i)=>[.5+(i%2?.003:-.003),.4,.01]);
  raw[30]=[0,0,0];const copy=JSON.parse(JSON.stringify(raw));
  const filtered=context.stabilizeMotionTrack(raw,30);
  const variation=track=>track.slice(2,27).reduce((sum,point,i)=>sum+Math.abs(point[0]-track[i+1][0]),0);
  assert.ok(variation(filtered)<variation(raw)*.5);
  assert.deepEqual(Array.from(filtered[30]),[0,0,0]);assert.deepEqual(raw,copy);
  const ramp=Array.from({length:30},(_,i)=>[.2+i*.01,.5,.01]);
  const steady=context.stabilizeMotionTrack(ramp,30);
  assert.ok(Math.abs(steady[15][0]-ramp[15][0])<.004,'a moving sign must not gain visible phase delay');
  assert.deepEqual(Array.from(context.sampleMotionTrack([[.2,.4,.1],[.4,.6,.2]],.5)),[.30000000000000004,.5,.15000000000000002]);
  assert.deepEqual(Array.from(context.sampleMotionTrack([[0,0,0],[.4,.6,.2]],.5)),[0,0,0],'interpolation never creates points across missing tracks');
});

test('animation clock preserves pauses and source time independently of display refresh rate',()=>{
  const samples=[],context={playbackGeneration:1,playTimer:1,lastPlaybackTime:null,paused:false,playbackElapsed:0,
    document:{querySelector:()=>({value:'1'})},requestAnimationFrame:()=>1,renderFrame:()=>samples.push(context.playbackElapsed)};
  vm.createContext(context);vm.runInContext(functions('function advanceMotion(','function playMotion('),context);
  [0,8,16,33,41].forEach(t=>context.advanceMotion(t));
  assert.ok(Math.abs(context.playbackElapsed-.041)<1e-9);assert.equal(samples.length,5);
  context.paused=true;context.advanceMotion(80);context.advanceMotion(110);assert.ok(Math.abs(context.playbackElapsed-.041)<1e-9);
  context.paused=false;context.advanceMotion(120);assert.ok(Math.abs(context.playbackElapsed-.051)<1e-9);
});

test('a fast rigid hand sweep does not acquire artificial finger bends from filtering',()=>{
  const context={};vm.createContext(context);
  vm.runInContext(functions('function handTracked(','function applyFacialMotion('),context);
  const raw=Array.from({length:40},(_,i)=>{
    const frame=Array(162).fill(0),wrist=.4+.12*Math.sin(i*.5);
    for(let j=0;j<21;j++){frame[j*3]=wrist+j*.001;frame[j*3+1]=.4+j*.008;frame[j*3+2]=.01+j*.001}
    frame[126]=.51;return frame;
  });
  const filtered=context.stabilizeHandTrack(raw,30);
  for(let i=0;i<raw.length;i++)for(let j=1;j<21;j++)for(let axis=0;axis<3;axis++){
    assert.ok(Math.abs((filtered[i][j*3+axis]-filtered[i][axis])-(raw[i][j*3+axis]-raw[i][axis]))<1e-10);
  }
  assert.equal(filtered[15][126],.51);assert.deepEqual(Array.from(filtered[15].slice(63,126)),Array(63).fill(0));
});

test('two clips transition through neutral and emit one completion for the whole queue',()=>{
  const node={value:0,textContent:''},bone=new THREE.Bone(),events=[];
  const next={sequence:[[.1,.2,.3],[.2,.3,.4]],label:'next',fps:24};
  let starts=0;
  const context={THREE,playTimer:1,lastPlaybackTime:null,playbackGeneration:0,playbackElapsed:0,
    frameIndex:0,activeSequence:[[1,2,3],[2,3,4]],activeFps:24,activeLabel:'first',activeLanguage:'kk-KZ',
    activeBodyPose:null,activeBodyPoseWorld:null,activeImageAspectRatio:1,motionTracks:{},neutralTransition:null,
    voiceQueue:[next],voiceMissing:[],document:{querySelector:()=>node},cancelAnimationFrame:()=>{},
    humanAvatar:{updateMatrixWorld:()=>{}},window:{parent:{postMessage:value=>events.push(value)}},
    applyNeutralPose:()=>bone.quaternion.identity(),normalizeImageAspectRatio:()=>1,renderSceneNow:()=>{},requestSceneRender:()=>{},
    playMotion:()=>{starts++;context.playTimer=2;context.playbackElapsed=0;context.neutralTransition=null},
  };
  vm.createContext(context);vm.runInContext(functions('function stopMotion(','function advanceMotion('),context);
  context.presentMotionSample=()=>bone.quaternion.setFromAxisAngle(new THREE.Vector3(0,1,0),1);
  context.presentMotionWithOpening=context.presentMotionSample;
  context.rigPoseBones=()=>[bone];
  context.playbackElapsed=2/24+.09;context.renderFrame();
  assert.ok(Math.abs(bone.quaternion.angleTo(new THREE.Quaternion())-.5)<1e-6,'neutral transition is a continuous slerp');
  assert.equal(starts,0);assert.equal(events.length,0);
  context.playbackElapsed=2/24+.2;context.renderFrame();
  assert.equal(starts,1);assert.equal(context.activeLabel,'next');assert.equal(events.length,0);
  context.playbackElapsed=2/24+.2;context.renderFrame();
  assert.equal(context.playTimer,null);assert.equal(events.length,1);assert.equal(events[0].type,'motion-ended');
});

test('opening skips only the low idle lead-in and blends from the arms-down pose',()=>{
  const context={handTracked:()=>true};vm.createContext(context);
  vm.runInContext(functions('function findOpeningRestEnd(','function stopMotion('),context);
  const frames=Array.from({length:56},(_,i)=>{const f=Array(162).fill(0);f[0]=.46;f[63]=.54;f[1]=f[64]=i<12?.78:.65;return f});
  const pose=[Array(18).fill(0)];pose[0][1]=pose[0][4]=.36;
  assert.equal(context.findOpeningRestEnd(frames,pose,24),12);
  frames[0][1]=frames[0][64]=.45;
  assert.equal(context.findOpeningRestEnd(frames,pose,24),0,'an already raised signing hand has no idle pre-roll');
  const bone=new THREE.Bone(),neutral=new THREE.Quaternion(),target=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),1);
  Object.assign(context,{THREE,humanRigBones:[bone],humanAvatar:{updateMatrixWorld:()=>{}},openingPose:null,openingRestEnd:12,activeFps:24,
    closingRestStart:null,applyNeutralPose:()=>bone.quaternion.copy(neutral),rigPoseBones:()=>[bone],presentMotionSample:()=>bone.quaternion.copy(target)});
  vm.runInContext(functions('function presentMotionWithOpening(','function renderFrame('),context);
  context.presentMotionWithOpening(0);assert.ok(bone.quaternion.angleTo(neutral)<1e-9);
  context.presentMotionWithOpening(12);assert.ok(bone.quaternion.angleTo(neutral)<1e-9);
  context.presentMotionWithOpening(12+24*.14);assert.ok(Math.abs(bone.quaternion.angleTo(neutral)-.5)<1e-6);
  context.presentMotionWithOpening(24);assert.ok(bone.quaternion.angleTo(target)<1e-9);
  const ending=frames.map((frame,i)=>{const f=frame.slice();f[1]=f[64]=i>=42?.78:.5;return f});
  const poseTrack=ending.map(()=>pose[0]);
  assert.equal(context.findClosingRestStart(ending,poseTrack,24),41);
  context.closingRestStart=41;
  context.presentMotionWithOpening(25);assert.ok(bone.quaternion.angleTo(target)<1e-9,'the active sign remains intact');
  context.presentMotionWithOpening(38);assert.ok(bone.quaternion.angleTo(neutral)>0&&bone.quaternion.angleTo(neutral)<1,'arms lower smoothly');
  for(const frame of [41,44,50,55]){context.presentMotionWithOpening(frame);assert.ok(bone.quaternion.angleTo(neutral)<1e-9,'the seated rest pose never returns in the trailing frames')}
});
