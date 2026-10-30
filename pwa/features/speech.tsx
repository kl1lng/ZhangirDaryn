'use client';
import {useEffect,useRef,useState} from 'react';
import {useI18n} from './locale';
import {Icon} from './icons';

type Result={isFinal:boolean;[index:number]:{transcript:string}};
type Recognition={lang:string;continuous:boolean;interimResults:boolean;maxAlternatives:number;onstart:(()=>void)|null;onend:(()=>void)|null;onerror:((event:{error:string})=>void)|null;onresult:((event:{resultIndex:number;results:ArrayLike<Result>})=>void)|null;start:()=>void;stop:()=>void;abort:()=>void};
type SpeechWindow=Window&{SpeechRecognition?:new()=>Recognition;webkitSpeechRecognition?:new()=>Recognition};

export function SpeechInput({onFinal}:{onFinal:(value:string)=>void}){
 const {t,locale}=useI18n();
 const [supported,setSupported]=useState<boolean|null>(null),[listening,setListening]=useState(false),[language,setLanguage]=useState('kk-KZ'),[interim,setInterim]=useState(''),[error,setError]=useState('');
 const active=useRef<Recognition|null>(null),callback=useRef(onFinal);
 useEffect(()=>{callback.current=onFinal;},[onFinal]);
 useEffect(()=>{
  const browser=window as SpeechWindow;
  setSupported(Boolean(browser.SpeechRecognition||browser.webkitSpeechRecognition));
  const hidden=()=>{if(document.hidden)active.current?.abort();};
  document.addEventListener('visibilitychange',hidden);
  return()=>{document.removeEventListener('visibilitychange',hidden);const recognition=active.current;if(recognition){recognition.onstart=null;recognition.onend=null;recognition.onresult=null;recognition.onerror=null;recognition.abort();}active.current=null;};
 },[]);
 useEffect(()=>{active.current?.abort();setLanguage(locale==='ru'?'ru-RU':locale==='en'?'en-US':'kk-KZ');},[locale]);
 function start(){
  if(active.current){active.current.stop();return;}
  const browser=window as SpeechWindow,Constructor=browser.SpeechRecognition||browser.webkitSpeechRecognition;
  if(!Constructor)return;
  setError('');setInterim('');
  const recognition=new Constructor(),accepted=new Set<number>();
  active.current=recognition;recognition.lang=language;recognition.continuous=false;recognition.interimResults=true;recognition.maxAlternatives=1;
  recognition.onstart=()=>setListening(true);
  recognition.onend=()=>{if(active.current===recognition)active.current=null;setListening(false);setInterim('');};
  recognition.onresult=event=>{let pending='';for(let i=event.resultIndex;i<event.results.length;i++){const result=event.results[i],text=result[0]?.transcript.trim();if(!text)continue;if(result.isFinal){if(!accepted.has(i)){accepted.add(i);callback.current(text);}}else pending+=text+' ';}setInterim(pending.trim());};
  recognition.onerror=event=>{if(event.error==='aborted')return;setError(event.error==='not-allowed'||event.error==='service-not-allowed'?'Разрешите доступ к микрофону в настройках браузера.':event.error==='no-speech'?'Речь не обнаружена. Попробуйте ещё раз.':'Не удалось распознать речь. Проверьте подключение и выбранный язык.');};
  try{recognition.start();}catch{active.current=null;setListening(false);setError('Не удалось запустить микрофон. Попробуйте ещё раз.');}
 }
 return <div className="speech-input">
  <strong>{locale==='kk'?'Сөйлеуді мәтінге айналдыру':locale==='en'?'Speech to text':'Речь в текст'}</strong>
  <div className="speech-controls"><button type="button" className="button secondary" disabled={!supported} aria-pressed={listening} onClick={start}><Icon name="mic" size={18}/>{listening?t('Остановить голосовой ввод'):t('Начать голосовой ввод')}</button>
  <label>{t('Язык речи')}<select value={language} disabled={listening} onChange={event=>setLanguage(event.target.value)}><option value="kk-KZ">Қазақша</option><option value="ru-RU">Русский</option><option value="en-US">English</option></select></label></div>
  <div role="status" aria-live="polite">{interim|| (listening?t('Слушаю…'):error?t(error):supported===false?t('Голосовой ввод недоступен в этом браузере.'):'')}</div>
  {supported===false&&<p>{locale==='kk'?'Дауыс енгізу үшін Chrome немесе Edge браузерін ашыңыз.':locale==='en'?'Open Chrome or Edge to use voice input.':'Для голосового ввода откройте сайт в Chrome или Edge.'}</p>}
  <small>{t('Аудио может обрабатываться сервисом вашего браузера. Результат можно исправить перед показом жестов.')}</small>
 </div>;
}
