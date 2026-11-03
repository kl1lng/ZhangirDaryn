// Offline arm-kinematics audit: runs the real avatar.html placement + IK code
// on the real Rocketbox skeleton for saved clip JSON files and reports where
// the avatar's wrists cannot follow the recorded pose.
// Usage: node scripts/audit-avatar-clips.cjs <dir-with-clip-json> [--csv out.csv]
// Uses body_pose_world_landmarks like the player does (--no-world to ignore them). Applies the pose-gap fill (--raw to skip). Limits: no hand-gap interpolation, smoothing,
// prepared-track corrections or finger posing.
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const THREE=require('three');
const html=fs.readFileSync(path.join(__dirname,'../web/avatar.html'),'utf8');
const slice=(from,to)=>html.slice(html.indexOf(from),html.indexOf(to,html.indexOf(from)));

function makeRig(){
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
  const context={THREE,humanAvatar:avatar,humanRigBones:bones,humanRigRest:rest,
    previousArmPole:[null,null],activeBodyPoseWorld:null,activeBodyPose:null,activeSequence:[],activeImageAspectRatio:1,
    rigFrameCorrections:[{depth:0,roll:0,contact:false},{depth:0,roll:0,contact:false}]};
  vm.createContext(context);
  vm.runInContext(slice('function calibrateMotion(','function midpoint(')+slice('function interpolateShortPoseGaps(','function sampleMotionTrack(')+slice('function bodyPosePoint(','function applyNeutralPose(')+slice('function placeRigSegment(','function palmBasis('),context);
  return{context,avatar,bones,rest,pos};
}

const percentile=(values,p)=>values.length?[...values].sort((a,b)=>a-b)[Math.min(values.length-1,Math.floor(values.length*p))]:0;

function auditClip(clip){
  const {context,avatar,bones,rest,pos}=makeRig();
  const pose=clip.metadata?.body_pose_landmarks;
  if(!Array.isArray(pose)||!pose.length)return null;
  const world=clip.metadata?.body_pose_world_landmarks;
  const track=process.argv.includes('--raw')?pose:context.interpolateShortPoseGaps(pose);
  context.activeBodyPose=track;context.activeSequence=clip.sequence;
  context.activeImageAspectRatio=Math.min(4,Math.max(.25,Number(clip.metadata.image_aspect_ratio)||1));
  vm.runInContext('calibrateMotion(activeSequence)',context);
  const placement=context.motionPlacement;
  const arm=side=>{const [a,b,c]=bones.slice(side*3,side*3+3);return pos(a).distanceTo(pos(b))+pos(b).distanceTo(pos(c))};
  const reach=[arm(0),arm(1)];
  const miss=[0,0],error=[[],[]],overReach=[0,0],speed=[[],[]],last=[null,null];
  const inside=[],insideDepth=[],elbowSpeed=[],lastElbow=[null,null];
  track.forEach((frame,index)=>{
    bones.forEach((bone,i)=>{bone.position.copy(rest[i].position);bone.quaternion.copy(rest[i].quaternion)});avatar.updateMatrixWorld(true);
    context.frame=frame;context.index=index;
    context.worldFrame=process.argv.includes('--no-world')?null:(world?.[index]||null);
    const pt=i=>vm.runInContext(`bodyPosePoint(frame,${i},index,worldFrame,false)`,context);
    const elbows=[pt(2),pt(3)],wrists=[pt(4),pt(5)];
    for(const side of [0,1]){
      const wrist=wrists[side],elbow=elbows[side];
      if(!wrist||!elbow){miss[side]++;last[side]=null;continue}
      context.elbow=elbow;context.wrist=wrist;
      vm.runInContext(`solveRigArm(${side*3},${side*3+1},${side*3+2},elbow,wrist,false)`,context);
      const shoulder=pos(bones[side*3]);
      // Target compared to where the wrist bone actually ended up.
      const got=pos(bones[side*3+2]);error[side].push(got.distanceTo(wrist));
      if(shoulder.distanceTo(wrist)>reach[side]*1.02)overReach[side]++;
      if(last[side])speed[side].push(got.distanceTo(last[side]));
      last[side]=got;
      // Torso envelope = the same front shell solveRigArm uses for its wrist correction (ellipse, 19 cm deep).
      // The wrist is corrected before IK, so check the points that are not: elbow, mid-forearm and the palm.
      const elbowP=pos(bones[side*3+1]),other=pos(bones[(1-side)*3]),mid=elbowP.clone().add(got).multiplyScalar(.5);
      const palm=got.clone().add(got.clone().sub(elbowP).normalize().multiplyScalar(.09));
      const cx=(shoulder.x+other.x)/2,half=Math.max(.18,Math.abs(shoulder.x-other.x)*.5),torsoY=(shoulder.y+other.y)/2,zc=(shoulder.z+other.z)/2;
      if(lastElbow[side])elbowSpeed.push(elbowP.distanceTo(lastElbow[side]));lastElbow[side]=elbowP;
      let deepest=0,which='';
      for(const [name,point] of [['elbow',elbowP],['forearm',mid],['palm',palm]]){
        const nx=(point.x-cx)/half;
        if(Math.abs(nx)<1&&point.y<torsoY-.06&&point.y>torsoY-.72){const d=zc+.19*Math.sqrt(1-nx*nx)-point.z;if(d>deepest){deepest=d;which=name}}
      }
      if(process.env.AUDIT_DEBUG&&deepest>.1){const f=v=>v.toFixed(2);console.log(`  frame ${index} side ${side} ${which} ${f(deepest)}m | targetWrist(${f(wrist.x)},${f(wrist.y)},${f(wrist.z)}) targetElbow(${f(elbow.x)},${f(elbow.y)},${f(elbow.z)}) shoulderZ ${f(zc)} torsoY ${f(torsoY)}`)}
      inside.push(deepest>.02?1:0);insideDepth.push(deepest);
    }
  });
  const n=track.length,all=[...error[0],...error[1]],spd=[...speed[0],...speed[1]];
  return{frames:n,
    poseWristMissing:(miss[0]+miss[1])/(2*n),
    unreachable:(overReach[0]+overReach[1])/(2*n),
    errP95:percentile(all,.95),errMax:Math.max(0,...all),
    speedP95:percentile(spd,.95),jumps:spd.filter(v=>v>.12).length,
    elbowJumps:elbowSpeed.filter(v=>v>.15).length,elbowP95:percentile(elbowSpeed,.95),
    intoTorso:inside.length?inside.reduce((x,y)=>x+y,0)/inside.length:0,intoTorsoP95:percentile(insideDepth,.95),intoTorsoMax:Math.max(0,...insideDepth),
    worldPerImageUnit:placement.worldPerImageUnit,reach:reach[0]};
}

const args=process.argv.slice(2),dir=args[0];
if(!dir){console.error('Usage: node scripts/audit-avatar-clips.cjs <dir> [--csv out.csv]');process.exit(2)}
const rows=[];
for(const file of fs.readdirSync(dir).filter(name=>name.endsWith('.json'))){
  let clip;try{clip=JSON.parse(fs.readFileSync(path.join(dir,file),'utf8'))}catch{continue}
  if(!Array.isArray(clip.sequence))continue;
  const result=auditClip(clip);if(result)rows.push({label:clip.label,id:path.basename(file,'.json'),...result});
}
rows.sort((a,b)=>(b.unreachable+b.poseWristMissing+b.jumps/b.frames)-(a.unreachable+a.poseWristMissing+a.jumps/a.frames));
const fmt=v=>typeof v==='number'?(Number.isInteger(v)?v:v.toFixed(3)):v;
const csv=['label,id,frames,poseWristMissing,unreachable,errP95_m,errMax_m,speedP95_m_per_frame,jumps,intoTorso,intoTorsoP95_m,intoTorsoMax_m,worldPerImageUnit']
  .concat(rows.map(r=>[JSON.stringify(r.label),r.id,r.frames,fmt(r.poseWristMissing),fmt(r.unreachable),fmt(r.errP95),fmt(r.errMax),fmt(r.speedP95),r.jumps,fmt(r.intoTorso),fmt(r.intoTorsoP95),fmt(r.intoTorsoMax),fmt(r.worldPerImageUnit)].join(','))).join('\n');
const out=args.indexOf('--csv');if(out>=0)fs.writeFileSync(args[out+1],'﻿'+csv);
const mean=key=>rows.reduce((s,r)=>s+r[key],0)/Math.max(1,rows.length);
console.log(`clips=${rows.length}  meanPoseWristMissing=${fmt(mean('poseWristMissing'))}  meanUnreachable=${fmt(mean('unreachable'))}  meanErrP95=${fmt(mean('errP95'))}m  meanJumps=${fmt(mean('jumps'))}  meanIntoTorso=${fmt(mean('intoTorso'))}  clipsIntoTorso>10%=${rows.filter(r=>r.intoTorso>.1).length}  clipsDepth>5cm=${rows.filter(r=>r.intoTorsoP95>.05).length}  elbowJumps/clip=${fmt(mean('elbowJumps'))}  elbowSpeedP95=${fmt(mean('elbowP95'))}m`);
