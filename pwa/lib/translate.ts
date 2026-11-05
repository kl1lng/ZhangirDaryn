import {resolvePhrase} from './gesture-search.ts';
import type {Gesture} from './types';

export type SignPlan={sequence:Gesture[];spelled:string[];lost:string[];ambiguous:{query:string;options:Gesture[]}[]};

// Text -> the signs to play, in order. A word without a sign is spelled with the letter signs, so a whole sentence plays;
// a word that cannot even be spelled (unknown letters, Latin text) is reported in `lost`.
export function planSigns(text:string,gestures:Gesture[],selected?:Gesture):SignPlan{
 const letters=new Map<string,Gesture>(gestures.filter(g=>Array.from(g.label.trim()).length===1).map(g=>[g.label.trim().toLowerCase(),g]));
 const spell=(word:string)=>Array.from(word.toLowerCase()).map(ch=>letters.get(ch)||(ch==='ё'?letters.get('е'):undefined)).filter((g):g is Gesture=>Boolean(g));
 const resolved=selected?{ambiguous:[],order:[{entry:selected as Gesture|undefined,word:undefined as string|undefined}]}:resolvePhrase(text,gestures);
 const sequence:Gesture[]=[],spelled:string[]=[],lost:string[]=[];
 for(const item of resolved.order){
  if(item.entry){sequence.push(item.entry);continue;}
  if(!item.word)continue;
  const signs=spell(item.word);
  if(signs.length){sequence.push(...signs);spelled.push(item.word);}else lost.push(item.word);
 }
 return {sequence,spelled,lost,ambiguous:resolved.ambiguous as SignPlan['ambiguous']};
}
