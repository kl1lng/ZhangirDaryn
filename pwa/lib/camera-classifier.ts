// Hand-only word classifier for the camera mode. The feature code must stay identical to scripts/camera_train.py.
// Input: landmarks of up to two hands per frame (x, y in 0..1 of the image, z in the same units as x); output: top words.
export type Point={x:number;y:number;z:number};
export type CameraModel={steps:number;features:number;hidden:number;classes:string[];mean:Float32Array;scale:Float32Array;threshold:number;w1:Float32Array;b1:Float32Array;w2:Float32Array;b2:Float32Array};
export type WordGuess={label:string;probability:number};
const FRAME=126;

// One frame: 2 hand slots x 21 landmarks x 3 numbers. Hands are ordered by wrist x (left in the image first), so no
// left/right label is needed. x and z are scaled by the image aspect so that distances are the same in every direction.
export function frameFromHands(hands:Point[][],aspect:number):Float32Array{
 const row=new Float32Array(FRAME);
 const valid=hands.filter(hand=>hand.length===21).sort((a,b)=>a[0].x-b[0].x).slice(0,2);
 valid.forEach((hand,slot)=>hand.forEach((point,i)=>{row[slot*63+i*3]=point.x*aspect;row[slot*63+i*3+1]=point.y;row[slot*63+i*3+2]=point.z*aspect;}));
 return row;
}
function resample(rows:Float32Array[],steps:number):Float32Array[]{
 return Array.from({length:steps},(_,i)=>{
  const at=steps>1?i*(rows.length-1)/(steps-1):0,lower=Math.floor(at),upper=Math.min(lower+1,rows.length-1),weight=at-lower;
  return rows[lower].map((value,j)=>value*(1-weight)+rows[upper][j]*weight);
 });
}
const present=(row:Float32Array,slot:number)=>Math.abs(row[slot*63])+Math.abs(row[slot*63+1])>0;
export function gestureFeatures(frames:Float32Array[],steps=12):Float32Array{
 const count=frames.length;
 const shape:Float32Array[]=[],wrist:Float32Array[]=[],palms:number[]=[],here:boolean[][]=[];
 for(const frame of frames){
  const shaped=new Float32Array(FRAME),wr=new Float32Array(6),flags=[false,false];
  for(let slot=0;slot<2;slot++){
   if(!present(frame,slot))continue;
   const base=slot*63,p=Math.hypot(frame[base+27]-frame[base],frame[base+28]-frame[base+1])+1e-6;
   for(let i=0;i<21;i++)for(let axis=0;axis<3;axis++)shaped[base+i*3+axis]=(frame[base+i*3+axis]-frame[base+axis])/p;
   for(let axis=0;axis<3;axis++)wr[slot*3+axis]=frame[base+axis];
   palms.push(p);flags[slot]=true;
  }
  shape.push(shaped);wrist.push(wr);here.push(flags);
 }
 let scale=1;
 if(palms.length){const sorted=[...palms].sort((a,b)=>a-b),mid=sorted.length>>1;scale=sorted.length%2?sorted[mid]:(sorted[mid-1]+sorted[mid])/2;}
 const mean=[new Float32Array(3),new Float32Array(3)];
 for(let slot=0;slot<2;slot++){let n=0;for(let t=0;t<count;t++)if(here[t][slot]){for(let a=0;a<3;a++)mean[slot][a]+=wrist[t][slot*3+a];n++;}if(n)for(let a=0;a<3;a++)mean[slot][a]/=n;}
 const traj:Float32Array[]=[],inter:Float32Array[]=[];
 for(let t=0;t<count;t++){
  const tr=new Float32Array(6),it=new Float32Array(3);
  for(let slot=0;slot<2;slot++)if(here[t][slot])for(let a=0;a<3;a++)tr[slot*3+a]=(wrist[t][slot*3+a]-mean[slot][a])/scale;
  if(here[t][0]&&here[t][1])for(let a=0;a<3;a++)it[a]=(wrist[t][3+a]-wrist[t][a])/scale;
  traj.push(tr);inter.push(it);
 }
 const out=new Float32Array(steps*(FRAME+6+3));let at=0;
 for(const part of [resample(shape,steps),resample(traj,steps),resample(inter,steps)])for(const row of part)for(const value of row)out[at++]=value;
 return out;
}
function halfToFloat(bits:number){
 const sign=bits&0x8000?-1:1,exponent=(bits>>10)&0x1f,fraction=bits&0x3ff;
 if(exponent===0)return sign*fraction*2**-24;
 if(exponent===31)return fraction?NaN:sign*Infinity;
 return sign*(1+fraction/1024)*2**(exponent-15);
}
export function parseModel(meta:Record<string,unknown>,buffer:ArrayBuffer):CameraModel{
 const features=Number(meta.features),hidden=Number(meta.hidden),classes=meta.classes as string[];
 if(meta.schema!==1||!Array.isArray(classes)||classes.length<2||classes.length>5000||!(features>0)||!(hidden>0))throw new Error('Invalid camera model');
 const sizes=[features*hidden,hidden,hidden*classes.length,classes.length];
 if(buffer.byteLength!==sizes.reduce((a,b)=>a+b,0)*2)throw new Error('Invalid camera model size');
 const bits=new Uint16Array(buffer);let at=0;
 const take=(size:number)=>{const array=new Float32Array(size);for(let i=0;i<size;i++)array[i]=halfToFloat(bits[at+i]);at+=size;return array;};
 const mean=Float32Array.from(meta.mean as number[]),scale=Float32Array.from(meta.scale as number[]);
 if(mean.length!==features||scale.length!==features)throw new Error('Invalid camera model scaler');
 return {steps:Number(meta.steps),features,hidden,classes,mean,scale,threshold:Number(meta.threshold)||.35,w1:take(sizes[0]),b1:take(sizes[1]),w2:take(sizes[2]),b2:take(sizes[3])};
}
export function classify(model:CameraModel,features:Float32Array,top=3):WordGuess[]{
 const {hidden,classes}=model,n=model.features,x=new Float32Array(n);
 for(let i=0;i<n;i++)x[i]=(features[i]-model.mean[i])/model.scale[i];
 const h=new Float32Array(model.b1);
 for(let i=0;i<n;i++){const value=x[i];if(!value)continue;const row=i*hidden;for(let j=0;j<hidden;j++)h[j]+=value*model.w1[row+j];}
 for(let j=0;j<hidden;j++)if(h[j]<0)h[j]=0;
 const logits=new Float32Array(model.b2);
 for(let j=0;j<hidden;j++){const value=h[j];if(!value)continue;const row=j*classes.length;for(let k=0;k<classes.length;k++)logits[k]+=value*model.w2[row+k];}
 let max=-Infinity;for(const v of logits)if(v>max)max=v;
 let sum=0;for(let k=0;k<logits.length;k++){logits[k]=Math.exp(logits[k]-max);sum+=logits[k];}
 return Array.from(logits,(v,k)=>({label:classes[k],probability:v/sum})).sort((a,b)=>b.probability-a.probability).slice(0,top);
}
