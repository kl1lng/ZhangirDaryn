/* Camera frames stay in this worker. Only public reference data is downloaded. */
importScripts('/camera/vision.js');
const cameraVision=self.exports;
self.exports={};
importScripts('/camera/matcher.js');
const cameraMatcher=self.exports;
self.exports={};
importScripts('/camera/classifier.js');
const cameraClassifier=self.exports;
let detector=null,references=[],frames=[],lastMatch=-Infinity,missing=0,wordModel=null,timed=[];
let latestCandidates=[],lastTop='';
// Words come from the trained model; the example library answers only for a held, still hand (letters), so that every
// hand shape is not forced onto the nearest letter.
function recognise(now){
 const window=timed.filter(item=>now-item.time<=1600);
 if(wordModel&&window.length>=10){
  const guesses=cameraClassifier.classify(wordModel,cameraClassifier.gestureFeatures(window.map(item=>item.frame),wordModel.steps),3);
  const best=guesses.filter(item=>item.probability>=wordModel.threshold);
  if(best.length){const stable=best[0].label===lastTop;lastTop=best[0].label;if(stable)return best.map(item=>({id:'',label:item.label,distance:1-item.probability}));return [];}
  lastTop='';
 }
 if(references.length&&frames.length>=12&&isHeldStill(frames))return cameraMatcher.rankExamples(frames,references);
 return [];
}
function isHeldStill(rows){
 const recent=rows.slice(-12);let travel=0;
 for(let i=1;i<recent.length;i++)for(const base of [0,63])travel+=Math.hypot(recent[i][base]-recent[i-1][base],recent[i][base+1]-recent[i-1][base+1]);
 return travel/recent.length<.006;
}
self.onmessage=async({data})=>{
 if(data.type==='init'){
  try{
   self.postMessage({type:'progress',stage:'model'});
   const files=await cameraVision.FilesetResolver.forVisionTasks('/camera/wasm');
   detector=await cameraVision.HandLandmarker.createFromOptions(files,{baseOptions:{modelAssetPath:'/camera/hand_landmarker.task',delegate:'CPU'},runningMode:'VIDEO',numHands:2,minHandDetectionConfidence:.6,minHandPresenceConfidence:.6,minTrackingConfidence:.6});
   self.postMessage({type:'progress',stage:'references'});
   // The word model is local and needed; the shared example library is optional (letters and own recordings).
   try{
    const [meta,weights]=await Promise.all([fetch('/camera/model.json',{credentials:'omit'}).then(r=>{if(!r.ok)throw new Error('model');return r.json();}),fetch('/camera/model.bin',{credentials:'omit'}).then(r=>{if(!r.ok)throw new Error('model');return r.arrayBuffer();})]);
    wordModel=cameraClassifier.parseModel(meta,weights);
   }catch{wordModel=null;}
   if(data.referenceUrl){
   const response=await fetch(data.referenceUrl,{credentials:'omit'});
     if(!response.ok)throw new Error('Reference download failed');
     const bundle=await response.json();
     if(bundle.schema!==1||!Array.isArray(bundle.references)||bundle.references.length>2000)throw new Error('Invalid reference bundle');
     const seen=new Set();
     references=bundle.references.filter(row=>{if(!row||typeof row.id!=='string'||typeof row.label!=='string'||!Array.isArray(row.sequence)||row.sequence.length>3600)throw new Error('Invalid reference');const key=row.label+'\n'+JSON.stringify(row.sequence);if(seen.has(key))return false;seen.add(key);return true;}).map(cameraMatcher.prepareReference);
     if(new Set(references.map(row=>row.label)).size<2)throw new Error('Not enough reference classes');
   }
   if(!wordModel&&!references.length)throw new Error('No camera data');
   self.postMessage({type:'ready',count:references.length+(wordModel?wordModel.classes.length:0)});
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
  if(!hasHands){missing++;latestCandidates=[];if(missing>=3){frames=[];timed=[];}}
  else {missing=0;frames.push(row);if(frames.length>30)frames.shift();timed.push({time:data.timestamp,frame:cameraClassifier.frameFromHands(result.landmarks,bitmap.width/bitmap.height)});while(timed.length&&data.timestamp-timed[0].time>2000)timed.shift();}
  if(hasHands&&data.timestamp-lastMatch>=400){lastMatch=data.timestamp;latestCandidates=recognise(data.timestamp);}
  self.postMessage({type:'result',hands:result.landmarks.length,landmarks:result.landmarks.map(hand=>hand.map(({x,y})=>({x,y}))),candidates:hasHands?latestCandidates:[],collecting:frames.length<12});
 }catch{self.postMessage({type:'error',code:'detection'});}
 finally{bitmap?.close();}
};
