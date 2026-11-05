'use client';
import {useCallback,useEffect,useRef,useState} from 'react';
import {useI18n} from './locale';
import {Icon} from './icons';
import {Player} from './player';
import {PageHeading} from './workspace';
import {api} from '@/lib/client';
import {loadGestures} from '@/lib/catalog';
import {planSigns} from '@/lib/translate';
import type {Gesture,Motion} from '@/lib/types';

type Result={isFinal:boolean;[index:number]:{transcript:string}};
type Recognition={lang:string;continuous:boolean;interimResults:boolean;maxAlternatives:number;onstart:(()=>void)|null;onend:(()=>void)|null;onerror:((event:{error:string})=>void)|null;onresult:((event:{resultIndex:number;results:ArrayLike<Result>})=>void)|null;start:()=>void;stop:()=>void;abort:()=>void};
type SpeechWindow=Window&{SpeechRecognition?:new()=>Recognition;webkitSpeechRecognition?:new()=>Recognition};
type Line={id:number;text:string;signs:Gesture[];spelled:string[];status:'waiting'|'playing'|'done'|'skipped'|'nosign'};
type WakeLock={release:()=>Promise<void>};
const MAX_WAITING=3,JOURNAL=6;

// Live mode: the microphone is recognised continuously and every phrase is queued for the avatar. At most three phrases wait;
// when speech is faster than the avatar, the oldest waiting phrases are skipped and the page says so.
export function Listen(){
 const {t,locale}=useI18n();
 const [supported,setSupported]=useState<boolean|null>(null);
 const [listening,setListening]=useState(false),[language,setLanguage]=useState('kk-KZ'),[interim,setInterim]=useState(''),[error,setError]=useState('');
 const [lines,setLines]=useState<Line[]>([]),[motions,setMotions]=useState<Motion[]>([]),[skipped,setSkipped]=useState(0);
 const wanted=useRef(false),recognition=useRef<Recognition|null>(null),gesturesRef=useRef<Gesture[]>([]),nextId=useRef(1);
 const waiting=useRef<Line[]>([]),playing=useRef<Line|null>(null),cache=useRef(new Map<string,Motion>()),wake=useRef<WakeLock|null>(null);
 useEffect(()=>{loadGestures().then(rows=>{gesturesRef.current=rows;}).catch(()=>{});},[]);
 useEffect(()=>{const browser=window as SpeechWindow;setSupported(Boolean(browser.SpeechRecognition||browser.webkitSpeechRecognition));},[]);
 useEffect(()=>{setLanguage(locale==='ru'?'ru-RU':locale==='en'?'en-US':'kk-KZ');},[locale]);

 const update=useCallback((id:number,status:Line['status'])=>setLines(rows=>rows.map(row=>row.id===id?{...row,status}:row)),[]);
 const pump=useCallback(async():Promise<void>=>{
  if(playing.current||!waiting.current.length)return;
  const line=waiting.current.shift()!;playing.current=line;update(line.id,'playing');
  try{
   const found:Motion[]=[];
   for(const sign of line.signs){
    let motion=cache.current.get(sign.id);
    if(!motion){motion=await api<Motion>(`gestures/${sign.id}/motion`);cache.current.set(sign.id,motion);}
    found.push(motion);
   }
   setMotions(found);
  }catch{playing.current=null;update(line.id,'skipped');void pump();}
 },[update]);
 const finished=useCallback(()=>{const line=playing.current;if(line)update(line.id,'done');playing.current=null;void pump();},[update,pump]);

 const accept=useCallback((text:string)=>{
  const plan=planSigns(text,gesturesRef.current);
  const line:Line={id:nextId.current++,text,signs:plan.sequence,spelled:plan.spelled,status:plan.sequence.length?'waiting':'nosign'};
  setLines(rows=>[line,...rows].slice(0,JOURNAL));
  if(!plan.sequence.length)return;
  waiting.current.push(line);
  let dropped=0;
  while(waiting.current.length>MAX_WAITING){const old=waiting.current.shift()!;update(old.id,'skipped');dropped++;}
  if(dropped)setSkipped(count=>count+dropped);
  void pump();
 },[pump,update]);

 const acquireWake=useCallback(async()=>{try{const nav=navigator as Navigator&{wakeLock?:{request:(type:'screen')=>Promise<WakeLock>}};if(nav.wakeLock&&!wake.current)wake.current=await nav.wakeLock.request('screen');}catch{wake.current=null;}},[]);
 const releaseWake=useCallback(()=>{void wake.current?.release().catch(()=>{});wake.current=null;},[]);

 const begin=useCallback(()=>{
  const browser=window as SpeechWindow,Constructor=browser.SpeechRecognition||browser.webkitSpeechRecognition;
  if(!Constructor||!wanted.current)return;
  const engine=new Constructor();recognition.current=engine;
  engine.lang=language;engine.continuous=true;engine.interimResults=true;engine.maxAlternatives=1;
  const done=new Set<number>();
  engine.onstart=()=>setListening(true);
  engine.onresult=event=>{
   let pending='';
   for(let i=event.resultIndex;i<event.results.length;i++){
    const result=event.results[i],text=result[0]?.transcript.trim();if(!text)continue;
    if(result.isFinal){if(!done.has(i)){done.add(i);accept(text);}}else pending+=text+' ';
   }
   setInterim(pending.trim());
  };
  engine.onerror=event=>{
   if(event.error==='aborted'||event.error==='no-speech')return;
   if(event.error==='not-allowed'||event.error==='service-not-allowed'){wanted.current=false;setError('Разрешите доступ к микрофону в настройках браузера.');}
   else setError('Не удалось распознать речь. Проверьте подключение к интернету.');
  };
  // Browsers end continuous recognition on their own after a pause; start again while the user wants to listen.
  engine.onend=()=>{
   if(recognition.current===engine)recognition.current=null;
   setInterim('');
   if(wanted.current&&!document.hidden)setTimeout(()=>{if(wanted.current&&!recognition.current)begin();},250);
   else setListening(false);
  };
  try{engine.start();}catch{recognition.current=null;setError('Не удалось запустить микрофон. Попробуйте ещё раз.');setListening(false);}
 },[language,accept]);

 const start=()=>{setError('');wanted.current=true;void acquireWake();begin();};
 const stop=useCallback(()=>{wanted.current=false;releaseWake();recognition.current?.stop();setListening(false);setInterim('');},[releaseWake]);
 useEffect(()=>{
  const visibility=()=>{if(document.hidden){stop();}else if(wanted.current)void acquireWake();};
  document.addEventListener('visibilitychange',visibility);
  return()=>{document.removeEventListener('visibilitychange',visibility);wanted.current=false;const engine=recognition.current;if(engine){engine.onstart=null;engine.onend=null;engine.onresult=null;engine.onerror=null;engine.abort();}recognition.current=null;releaseWake();};
 },[stop,acquireWake,releaseWake]);

 const state:Record<Line['status'],string>={waiting:t('В очереди'),playing:t('Показывается'),done:t('Показано'),skipped:t('Пропущено'),nosign:t('Нет жестов')};
 const languages:[string,string][]=[['kk-KZ','Қазақша'],['ru-RU','Русский'],['en-US','English']];
 const label=listening?t("Остановить прослушивание"):t("Начать слушать");
 const live=interim||(listening?t('Слушаю…'):error?t(error):supported===false?t('Голосовой ввод недоступен в этом браузере.'):t('Пока ничего не слышно.'));
 return <><PageHeading title={t("Слушаю и показываю")} text={t("Включите микрофон: речь вокруг превратится в жесты.")} aside={<span className="section-tag"><Icon name="mic" size={17}/>{t("Прямой показ")}</span>}/>
  <div className="translate-layout"><section className="compose-panel listen-panel">
   <div className={'listen-stage'+(listening?' is-live':'')}>
    <button type="button" className="mic-orb" aria-pressed={listening} disabled={supported===false} onClick={()=>listening?stop():start()}>
     <span className="orb-ring" aria-hidden="true"/><span className="orb-ring r2" aria-hidden="true"/>
     <span className="orb-core" aria-hidden="true"><Icon name="mic" size={34}/></span>
     <span className="sr-only">{label}</span>
    </button>
    <p className="stage-title" aria-hidden="true">{listening?t("Слушаю…"):label}</p>
    <div className="seg" role="radiogroup" aria-label={t("Язык речи")}>{languages.map(([code,name])=><button type="button" role="radio" aria-checked={language===code} key={code} className={language===code?'on':''} disabled={listening} onClick={()=>setLanguage(code)}>{name}</button>)}</div>
   </div>
   <div className={'listen-live'+(interim?' has-text':'')} role="status" aria-live="polite"><span className="eyebrow">{t("Сейчас слышу")}</span><p>{live}</p></div>
   {error&&listening&&<p className="error" role="alert">{t(error)}</p>}
   {skipped>0&&<div className="warning" role="status">{t("Речь быстрее показа: пропущено фраз")}: {skipped}. {t("Показываю последние.")}</div>}
   <div className="listen-head"><h3 className="listen-title">{t("Недавние фразы")}</h3>{lines.length>0&&<button type="button" className="link-button" onClick={()=>{setLines([]);setSkipped(0);}}>{t("Очистить")}</button>}</div>
   {lines.length?<ol className="listen-journal">{lines.map(line=><li key={line.id} className={'line-'+line.status}><span className="line-dot" aria-hidden="true"/><span className="line-text">{line.text}{line.spelled.length>0&&<em>{t("по буквам")}: {line.spelled.join(', ')}</em>}</span><span className="line-state">{state[line.status]}</span></li>)}</ol>:<div className="listen-empty"><Icon name="hand" size={26}/><p>{t("Здесь появятся услышанные фразы, а рядом их показ жестами.")}</p></div>}
   <details className="listen-note"><summary><Icon name="shield" size={17}/>{t("О приватности и точности")}</summary><p>{t("Речь распознаёт браузер: в Chrome и Edge звук обрабатывает облачная служба браузера. Мы ничего не записываем и не сохраняем.")}</p><p>{t("Показ отдельных жестов не заменяет полноценный перевод предложения. Понятность движения требует проверки носителями КЖЯ.")}</p></details>
  </section><Player motions={motions} onEnded={finished} defaultSpeed="1.5" label="Прямой показ"/></div></>;
}
