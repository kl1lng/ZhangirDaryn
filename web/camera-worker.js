/* Camera frames stay in this worker. Only public reference data is downloaded. */
importScripts('/camera/vision.js');
const cameraVision=self.exports;
self.exports={};
importScripts('/camera/matcher.js');
const cameraMatcher=self.exports;
let detector=null,references=[],frames=[],lastMatch=-Infinity,missing=0;
let latestCandidates=[];
self.onmessage=async({data})=>{
 if(data.type==='init'){
  try{
   self.postMessage({type:'progress',stage:'model'});
   const files=await cameraVision.FilesetResolver.forVisionTasks('/camera/wasm');
   detector=await cameraVision.HandLandmarker.createFromOptions(files,{baseOptions:{modelAssetPath:'/camera/hand_landmarker.task',delegate:'CPU'},runningMode:'VIDEO',numHands:2,minHandDetectionConfidence:.6,minHandPresenceConfidence:.6,minTrackingConfidence:.6});
   self.postMessage({type:'progress',stage:'references'});
   const response=await fetch(data.referenceUrl,{credentials:'omit'});
   if(!response.ok)throw new Error('Reference download failed');
   const bundle=await response.json();
   if(bundle.schema!==1||!Array.isArray(bundle.references)||bundle.references.length>2000)throw new Error('Invalid reference bundle');
   const seen=new Set();
   references=bundle.references.filter(row=>{if(!row||typeof row.id!=='string'||typeof row.label!=='string'||!Array.isArray(row.sequence)||row.sequence.length>3600)throw new Error('Invalid reference');const key=row.label+'\n'+JSON.stringify(row.sequence);if(seen.has(key))return false;seen.add(key);return true;}).map(cameraMatcher.prepareReference);
   if(new Set(references.map(row=>row.label)).size<2)throw new Error('Not enough reference classes');
   self.postMessage({type:'ready',count:references.length});
  }catch{detector?.close();detector=null;self.postMessage({type:'error',code:'initialization'});}
  return;
 }
 if(data.type!=='frame')return;
 const bitmap=data.bitmap;
 try{
  if(!detector)return;
  const result=detector.detectForVideo(bitmap,data.timestamp);
  const row=cameraMatcher.handFeatures(result.landmarks,result.handedness);
  const hasHands=row.some(value=>value!==0);
  if(!hasHands){missing++;latestCandidates=[];if(missing>=3)frames=[];}
  else {missing=0;frames.push(row);if(frames.length>30)frames.shift();}
  if(hasHands&&data.timestamp-lastMatch>=500){lastMatch=data.timestamp;latestCandidates=cameraMatcher.rankExamples(frames,references);}
  self.postMessage({type:'result',hands:result.landmarks.length,landmarks:result.landmarks.map(hand=>hand.map(({x,y})=>({x,y}))),candidates:hasHands?latestCandidates:[],collecting:frames.length<12});
 }catch{self.postMessage({type:'error',code:'detection'});}
 finally{bitmap?.close();}
};
