// Experimental hand-only nearest-example matching. Distances are not probabilities.
type Point={x:number;y:number;z:number};
export type CameraReference={id:string;label:string;sequence:number[][]};
type Prepared={id:string;label:string;sample:number[][]};
export type CameraCandidate={id:string;label:string;distance:number};
const STEPS=16,MAX_DISTANCE=.22;
const visible=(row:number[],side:number)=>{
 const start=side*63;
 for(let i=1;i<21;i++)if(Math.hypot(row[start+i*3]-row[start],row[start+i*3+1]-row[start+1])>.012)return true;
 return false;
};
export function handFeatures(hands:Point[][],handedness:{categoryName:string;score:number}[][]){
 const row=Array<number>(126).fill(0);
 hands.forEach((hand,i)=>{
  const category=handedness[i]?.[0];
  if(hand.length!==21||!category||category.score<.5||!['Left','Right'].includes(category.categoryName))return;
  // MediaPipe assumes a mirrored selfie; camera pixels here are unmirrored.
  const start=category.categoryName==='Right'?0:63;
  hand.forEach((point,j)=>{row[start+j*3]=point.x;row[start+j*3+1]=point.y;row[start+j*3+2]=point.z;});
 });
 return row;
}
function resample(rows:number[][]){
 return Array.from({length:STEPS},(_,i)=>{const at=i*(rows.length-1)/(STEPS-1),a=Math.floor(at),b=Math.min(a+1,rows.length-1),weight=at-a;return rows[a].map((value,j)=>value*(1-weight)+rows[b][j]*weight);});
}
export function normalizeHands(rows:number[][]){
 if(!rows.length||rows.some(row=>row.length<126||row.slice(0,126).some(x=>!Number.isFinite(x))))throw new Error('Invalid hand sequence');
 let scale=0;
 for(const row of rows)for(let side=0;side<2;side++){
  if(!visible(row,side))continue;
  const start=side*63;
  for(let a=0;a<21;a++)for(let b=a+1;b<21;b++)scale=Math.max(scale,Math.hypot(...[0,1,2].map(axis=>row[start+a*3+axis]-row[start+b*3+axis])));
 }
 if(scale<1e-8)return rows.map(()=>Array<number>(126).fill(0));
 return rows.map(row=>Array.from({length:126},(_,i)=>{
  const side=i<63?0:1;if(!visible(row,side))return 0;
  // Same shared scale and frame-center anchor as Python normalize_sequence.
  return (row[i]-(i%3===2?0:.5))/scale;
 }));
}
export function prepareReference(reference:CameraReference):Prepared{
 return {id:reference.id,label:reference.label,sample:resample(normalizeHands(reference.sequence))};
}
function temporalDistance(query:number[][],reference:number[][]){
 const costs=Array.from({length:STEPS+1},()=>Array<number>(STEPS+1).fill(Infinity));
 const lengths=Array.from({length:STEPS+1},()=>Array<number>(STEPS+1).fill(0));costs[0][0]=0;
 for(let i=1;i<=STEPS;i++)for(let j=Math.max(1,i-3);j<=Math.min(STEPS,i+3);j++){
  let sum=0,weight=0;
  for(let side=0;side<2;side++){
   const q=visible(query[i-1],side),r=visible(reference[j-1],side);if(!q&&!r)continue;
   if(q&&r){let error=0;for(let k=side*63;k<(side+1)*63;k++)error+=Math.abs(query[i-1][k]-reference[j-1][k]);sum+=error/63;weight++;}
   else {sum+=.25;weight+=.5;}
  }
  const choices=[[i-1,j-1],[i-1,j],[i,j-1]].sort((a,b)=>costs[a[0]][a[1]]-costs[b[0]][b[1]]),[a,b]=choices[0];
  costs[i][j]=costs[a][b]+(weight?sum/weight:.5);lengths[i][j]=lengths[a][b]+1;
 }
 return costs[STEPS][STEPS]/lengths[STEPS][STEPS];
}
export function rankExamples(sequence:number[][],references:Prepared[]):CameraCandidate[]{
 if(sequence.length<12||!references.length)return [];
 if(sequence.filter(row=>visible(row,0)||visible(row,1)).length/sequence.length<.6)return [];
 const windows=[12,20,30].filter(size=>size<=sequence.length).map(size=>resample(normalizeHands(sequence.slice(-size))));
 const classes=new Map<string,CameraCandidate>();
 for(const reference of references){
  const distance=Math.min(...windows.map(query=>temporalDistance(query,reference.sample)));
  const key=reference.label.normalize('NFC').toLowerCase().replace(/[_\s]+/g,' ').trim();
  if(distance<=MAX_DISTANCE&&(!classes.has(key)||distance<classes.get(key)!.distance))classes.set(key,{id:reference.id,label:reference.label,distance});
 }
 const ranked=[...classes.values()].sort((a,b)=>a.distance-b.distance);
 return ranked.filter(item=>item.distance<=ranked[0].distance+.08).slice(0,3);
}
