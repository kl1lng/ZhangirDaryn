// Prepared local bone rotations. No source landmarks or bind offsets are edited.
export const RIG_MOTION_VERSION='rocketbox-02-prepared-v2';

function createRigBake({bones,frameCount,fps,solveFrame,groups=[],tracked=()=>[]}){
  if(!bones.length||!Number.isInteger(frameCount)||frameCount<1||frameCount>18000||!Number.isFinite(fps)||fps<1||fps>240)
    throw new Error('Некорректная длительность анимации.');
  const neutral=bones.map(b=>b.quaternion.clone()),last=neutral.map(q=>q.clone());
  const lastTracked=neutral.map(q=>q.clone()),missing=groups.map(()=>0);
  const rotations=new Float32Array(frameCount*bones.length*4);
  const quality={missingFrames:groups.map(()=>0),limitedRotations:0};
  function bakeFrame(frame){
    solveFrame(frame);
    const valid=tracked(frame);
    groups.forEach((indices,side)=>{
      if(valid[side]!==false){missing[side]=0;indices.forEach(i=>lastTracked[i].copy(bones[i].quaternion));return}
      missing[side]++;quality.missingFrames[side]++;
      const amount=Math.min(1,Math.max(0,(missing[side]/fps-.12)/.30));
      indices.forEach(i=>bones[i].quaternion.slerpQuaternions(lastTracked[i],neutral[i],amount));
    });
    bones.forEach((bone,i)=>{
      const q=bone.quaternion;
      if(![q.x,q.y,q.z,q.w].every(Number.isFinite)||q.lengthSq()<1e-8)
        throw new Error(`Некорректный поворот кости ${bone.name}, кадр ${frame}.`);
      q.normalize();
      // Limit tracker flips; retain an explicit warning rather than certifying
      // an automatically altered sign as linguistically correct.
      const angle=last[i].angleTo(q),limit=24/fps;
      if(frame&&angle>limit){q.slerpQuaternions(last[i],q.clone(),limit/angle);quality.limitedRotations++}
      if(q.dot(last[i])<0)q.set(-q.x,-q.y,-q.z,-q.w);
      q.toArray(rotations,(frame*bones.length+i)*4);last[i].copy(q);
    });
  }
  return {
    bakeFrame,
    finish(){return{version:RIG_MOTION_VERSION,boneNames:bones.map(b=>b.name),frameCount,fps,rotations,quality}},
  };
}

export function bakeRigMotion(options){
  const task=createRigBake(options);
  for(let frame=0;frame<options.frameCount;frame++)task.bakeFrame(frame);
  return task.finish();
}

export async function bakeRigMotionAsync(options){
  const {chunkSize=2,yieldControl=()=>new Promise(resolve=>setTimeout(resolve,0)),signal,onChunk}=options;
  if(!Number.isInteger(chunkSize)||chunkSize<1)throw new Error('Некорректный размер порции подготовки.');
  const checkCancelled=()=>{if(signal?.aborted){const error=new Error('Подготовка устаревшего движения отменена.');error.name='AbortError';throw error}};
  const task=createRigBake(options);
  let chunkStarted=globalThis.performance?.now?.()??Date.now();
  for(let frame=0;frame<options.frameCount;frame++){
    checkCancelled();task.bakeFrame(frame);
    if((frame+1)%chunkSize===0&&frame+1<options.frameCount){
      const now=globalThis.performance?.now?.()??Date.now();
      onChunk?.({fromFrame:frame+1-chunkSize,toFrame:frame,durationMs:now-chunkStarted});
      await yieldControl();checkCancelled();chunkStarted=globalThis.performance?.now?.()??Date.now();
    }
  }
  return task.finish();
}

export function isPreparedMotion(data,bones,frameCount,fps){
  if(!data||data.version!==RIG_MOTION_VERSION||data.frameCount!==frameCount||data.fps!==fps||
    !data.quality||!Array.isArray(data.quality.missingFrames)||
    !Number.isInteger(data.quality.limitedRotations)||data.quality.limitedRotations<0||
    data.quality.missingFrames.some(n=>!Number.isInteger(n)||n<0||n>frameCount)||
    !Array.isArray(data.boneNames)||data.boneNames.length!==bones.length||
    data.boneNames.some((name,i)=>name!==bones[i].name)||
    !(data.rotations instanceof Float32Array)||data.rotations.length!==frameCount*bones.length*4)return false;
  for(let i=0;i<data.rotations.length;i+=4){
    const q=data.rotations.subarray(i,i+4),norm=q.reduce((sum,n)=>sum+n*n,0);
    if(!Number.isFinite(norm)||Math.abs(norm-1)>.001)return false;
  }
  return true;
}

export function applyPreparedFrame(data,bones,position){
  if(!Number.isFinite(position))throw new Error('Некорректная позиция анимации.');
  const p=Math.max(0,Math.min(data.frameCount-1,position)),a=Math.floor(p),b=Math.min(a+1,data.frameCount-1);
  bones.forEach((bone,i)=>{
    const offset=(a*bones.length+i)*4,next=(b*bones.length+i)*4;
    const target=bone.quaternion.clone().fromArray(data.rotations,next);
    bone.quaternion.fromArray(data.rotations,offset).slerp(target,p-a).normalize();
  });
}

export async function motionFingerprint(source){
  const bytes=new TextEncoder().encode(JSON.stringify([RIG_MOTION_VERSION,source]));
  const hash=await crypto.subtle.digest('SHA-256',bytes);
  return [...new Uint8Array(hash)].map(n=>n.toString(16).padStart(2,'0')).join('');
}

export function correctionAt(edits,frame,side,fps){
  const value={depth:0,roll:0,contact:false};
  for(const edit of edits){
    if(edit.side!==side||frame<edit.from||frame>edit.to)continue;
    const fade=Math.max(1,Math.min(fps*.10,(edit.to-edit.from+1)/2));
    const t=Math.min(1,(frame-edit.from+1)/fade,(edit.to-frame+1)/fade);
    const weight=t*t*(3-2*t);
    value.depth+=(Number(edit.depth)||0)*weight;value.roll+=(Number(edit.roll)||0)*weight;
    if(edit.contact)value.contact=true;
  }
  return value;
}

// Storage failure never prevents playback. The caller must disclose whether
// the prepared result was persisted; private browsing may disable IndexedDB.
export async function motionStore(action,key,value){
  if(typeof indexedDB==='undefined')throw new Error('Локальное хранилище недоступно.');
  const db=await new Promise((resolve,reject)=>{
    const request=indexedDB.open('dosym-prepared-motion',1);
    let expired=false;
    const timer=setTimeout(()=>{expired=true;reject(new Error('Хранилище не отвечает.'))},2500);
    request.onupgradeneeded=()=>request.result.createObjectStore('clips');
    request.onblocked=()=>{expired=true;clearTimeout(timer);reject(new Error('Закройте старую вкладку аватара.'))};
    request.onerror=()=>{clearTimeout(timer);reject(request.error)};
    request.onsuccess=()=>{clearTimeout(timer);if(expired)request.result.close();else resolve(request.result)};
  });
  try{
    return await new Promise((resolve,reject)=>{
      const tx=db.transaction('clips',action==='get'?'readonly':'readwrite');
      const store=tx.objectStore('clips'),request=action==='get'?store.get(key):store.put(value,key);
      const timer=setTimeout(()=>{tx.abort();reject(new Error('Хранилище не отвечает.'))},5000);
      tx.oncomplete=()=>{clearTimeout(timer);resolve(action==='get'?request.result:true)};
      tx.onerror=()=>{clearTimeout(timer);reject(tx.error)};
      tx.onabort=()=>{clearTimeout(timer);reject(tx.error||new Error('Сохранение прервано.'))};
    });
  }finally{db.close()}
}

export function createMotionRepository(storage=motionStore){
  const memory=new Map();
  return{
    async get(key){
      if(memory.has(key))return {...memory.get(key),source:'memory'};
      try{
        const record=await storage('get',key);
        if(record){const entry={record,persisted:true};memory.set(key,entry);return {...entry,source:'browser'}}
      }catch{/* In-memory edits must survive even when IndexedDB is disabled. */}
      return {record:null,persisted:false,source:'none'};
    },
    async put(key,record){
      const entry={record,persisted:false};memory.set(key,entry);
      try{await storage('put',key,record);entry.persisted=true}catch{/* Playback remains usable in this tab. */}
      return entry.persisted;
    },
  };
}
