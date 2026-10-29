// Search compatibility, not an orthographic converter. Stored labels are never rewritten.
// Alphabet reference: https://www.gov.kz/org/mfa-omsk/press/news/details/153331
export const KAZAKH_LATIN:Record<string,string>={
 а:'a',ә:'ä',б:'b',в:'v',г:'g',ғ:'ğ',д:'d',е:'e',ё:'yo',ж:'j',з:'z',и:'i',й:'i',
 к:'k',қ:'q',л:'l',м:'m',н:'n',ң:'ñ',о:'o',ө:'ö',п:'p',р:'r',с:'s',т:'t',у:'u',
 ұ:'ū',ү:'ü',ф:'f',х:'h',һ:'h',ц:'ts',ч:'ch',ш:'ş',щ:'şş',ъ:'ʺ',ы:'y',і:'ı',ь:'ʹ',э:'e',ю:'yu',я:'ya',
};
type Entry={id:string;label:string;language?:string};
const native=(text:string)=>text.normalize('NFC').toLowerCase().replace(/\u0307/g,'').trim().replace(/[^\p{L}\p{N}ʹʺ]+/gu,' ').trim().replace(/\s+/g,' ');
const roman=(text:string,common=false)=>native(text).replace(/ŋ/g,'ñ').replace(/[а-яёәғқңөұүһі]/gu,c=>common&&c==='й'?'y':KAZAKH_LATIN[c]??c);
const folded=(text:string)=>text.normalize('NFD').replace(/\p{M}/gu,'').replace(/ı/g,'i').replace(/shch/g,'ss').replace(/zh/g,'j').replace(/gh/g,'g').replace(/ng/g,'n').replace(/sh/g,'s').replace(/kh/g,'h');
const preciseKey=(text:string)=>text.length>1?text.replace(/ı/g,'i'):text;
const unique=<T extends Entry>(rows:T[])=>rows.filter((row,i)=>rows.findIndex(other=>native(other.label)===native(row.label)&&other.language===row.language)===i);
export function uniqueGestures<T extends Entry>(rows:T[]){return unique(rows);}
export function matchGesture<T extends Entry>(query:string,rows:T[]){
 const original=native(query);
 if(!original)return {matches:[] as T[],ambiguous:false};
 const exact=unique(rows.filter(row=>native(row.label)===original));
 if(exact.length)return {matches:exact,ambiguous:exact.length>1};
 const key=roman(query),precise=/[^\x00-\x7F]/u.test(original);
 const matches=unique(rows.filter(row=>precise?preciseKey(roman(row.label))===preciseKey(key):
  [roman(row.label),roman(row.label,true)].some(label=>folded(label)===folded(key))));
 return {matches,ambiguous:matches.length>1};
}
export function searchGesture(label:string,query:string){
 const key=roman(query);
 if(!key)return true;
 if(/[^\x00-\x7F]/u.test(native(query)))return preciseKey(roman(label)).includes(preciseKey(key));
 return [roman(label),roman(label,true)].some(value=>folded(value).includes(folded(key)));
}
export function resolvePhrase<T extends Entry>(text:string,rows:T[]){
 const tokens=native(text).split(' ').filter(Boolean),matches:T[]=[],missing:string[]=[],ambiguous:{query:string;options:T[]}[]=[];
 const maxWords=Math.max(1,...rows.map(row=>native(row.label).split(' ').length));
 for(let i=0;i<tokens.length;){
  let consumed=0;
  for(let size=Math.min(maxWords,tokens.length-i);size>0;size--){
   const query=tokens.slice(i,i+size).join(' '),result=matchGesture(query,rows);
   if(!result.matches.length)continue;
   if(result.ambiguous)ambiguous.push({query,options:result.matches});else matches.push(result.matches[0]);
   consumed=size;break;
  }
  if(!consumed){missing.push(tokens[i]);consumed=1;}
  i+=consumed;
 }
 return {matches,missing,ambiguous};
}
