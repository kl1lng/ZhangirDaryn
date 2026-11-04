import {api,rslCatalog} from './client';
import type {Gesture} from './types';

// Display helper for the dictionary: every word starts with a capital letter (Kazakh casing rules).
export const capitalize=(label:string)=>{const text=label.trim();return text.charAt(0).toLocaleUpperCase('kk')+text.slice(1);};

// The library: our own recordings plus the bundled shared collection. Own recordings win when both have the same word.
export async function loadGestures():Promise<Gesture[]>{
 const [own,shared]=await Promise.all([api<Gesture[]>('gestures'),rslCatalog().catch(()=>[] as Gesture[])]);
 const byLabel=new Map(own.map(g=>[g.label.trim().toLowerCase(),g]));
 const extra:Gesture[]=[];
 for(const g of shared){
  const mine=byLabel.get(g.label.trim().toLowerCase());
  // The same word: keep our recording, but let the other spellings (for example the Russian word) find it too.
  if(mine){mine.aliases=[...new Set([...(mine.aliases||[]),...(g.aliases||[])])];}
  else extra.push(g);
 }
 return [...own,...extra];
}
