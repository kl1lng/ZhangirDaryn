'use client';
import {useI18n} from './locale';
import {useEffect,useRef,useState} from 'react';
import type { Motion } from '@/lib/types';
import {Icon} from './icons';
export function Player({motions=[],label='Пространство жеста'}:{motions?:Motion[];label?:string}){const {t,errorText}=useI18n();
 const frame=useRef<HTMLIFrameElement>(null);const [ready,setReady]=useState(false),[playing,setPlaying]=useState(false),[paused,setPaused]=useState(false),[error,setError]=useState('');
 const [speed,setSpeed]=useState('1');
 const [preparing,setPreparing]=useState(true);
 useEffect(()=>{setPreparing(true);},[motions]);
 useEffect(()=>{const receive=(event:MessageEvent)=>{if(event.origin!==location.origin||event.source!==frame.current?.contentWindow)return;if(event.data?.type==='avatar-preparing')setPreparing(true);if(event.data?.type==='avatar-frame-ready')setPreparing(false);};window.addEventListener('message',receive);return()=>window.removeEventListener('message',receive);},[]);
 function send(message:object){frame.current?.contentWindow?.postMessage(message,location.origin);}
 function play(){if(!motions.length)return;setPlaying(true);setPaused(false);send({type:'load-motion-queue',segments:motions.map(m=>({type:'motion',label:m.label,sequence:m.sequence,fps:m.fps,language:'kk-KZ',body_pose:m.metadata.body_pose_landmarks,body_pose_world:m.metadata.body_pose_world_landmarks,image_aspect_ratio:m.metadata.image_aspect_ratio})),missing:[]});}
 useEffect(()=>{if(!motions.length){setReady(false);setPlaying(false);setPaused(false);}},[motions.length]);
 useEffect(()=>{function message(event:MessageEvent){if(event.origin!==location.origin||event.source!==frame.current?.contentWindow)return;if(event.data?.type==='avatar-ready')setReady(true);if(event.data?.type==='motion-ended'){setPlaying(false);setPaused(false);}if(event.data?.type==='avatar-error')setError('На этом устройстве не удалось запустить 3D. Попробуйте другой браузер.');}window.addEventListener('message',message);return()=>window.removeEventListener('message',message);},[]);
 useEffect(()=>{if(ready&&motions.length)play();},[motions,ready]); // Commands are sent only after the frame is ready.
 useEffect(()=>{const doc=frame.current?.contentDocument;if(doc?.readyState==='complete'&&doc.location.pathname==='/avatar/index.html')setReady(true);},[]); // Cached frames may finish before React attaches load listeners.
 useEffect(()=>{if(!frame.current?.contentDocument)return;const el=frame.current.contentDocument.querySelector<HTMLSelectElement>('#motion-speed');if(el)el.value=speed;},[speed]);
 useEffect(()=>{const target=frame.current;if(!target)return;let inViewport=true;const sync=()=>{const visible=inViewport&&!document.hidden;send({type:'visibility',visible});if(!visible&&playing){send({type:'pause'});setPlaying(false);setPaused(true);}};const observer=new IntersectionObserver(entries=>{const entry=entries[0];inViewport=Boolean(entry?.isIntersecting&&entry.intersectionRatio>0);sync();},{threshold:[0,0.01]});observer.observe(target);document.addEventListener('visibilitychange',sync);return()=>{observer.disconnect();document.removeEventListener('visibilitychange',sync);};},[playing]);
 return <section className="player" aria-label={t("Проигрыватель жестов")}>
  <div className="stage-top"><span className="scene-label"><span className="tiny-dot"/>{t(label)}</span><span>{t("3D-аватар")}</span></div>
  <div className="scene-wrap">{motions.length?<iframe ref={frame} title={t("Аватар DosYm")} src="/avatar/index.html?v=prepared-frame-2" onLoad={()=>setReady(true)} onError={()=>setError('Не удалось загрузить сцену.')} />:<div className="avatar-placeholder" aria-label={t("Здесь появится ваш жест")}><Icon name="hand" size={38}/><span>{t("Здесь появится ваш жест")}</span></div>}
  {motions.length>0&&preparing&&!error&&<div className="avatar-placeholder" role="status" style={{position:'absolute',inset:0,background:'#eaf0f7'}}><Icon name="hand" size={38}/><span>{t('Подготавливаем движение…')}</span></div>}
  {error&&<p className="scene-error" role="status">{errorText(error)}</p>}
  <span className="scene-note">{t("Кисти, движение, смысл.")}</span></div>
  <div className="player-controls"><button className="round-button" aria-label={playing?t("Приостановить"):paused?t("Продолжить"):t("Воспроизвести")} disabled={!motions.length||!ready} onClick={()=>{if(playing){send({type:'pause'});setPlaying(false);setPaused(true);}else if(paused){send({type:'resume'});setPlaying(true);setPaused(false);}else play();}}><Icon name={playing?'pause':'play'}/></button>
   <div className="player-caption"><strong>{motions.length?motions.map(m=>m.label).join(' · '):t("Здесь появится ваш жест")}</strong><span>{motions.length?t("Движение по сохранённым координатам"):t("Найдите слово или добавьте запись")}</span></div>
   <label className="speed">{t("Скорость")}<select value={speed} onChange={e=>setSpeed(e.target.value)}><option value="0.5">0,5×</option><option value="0.75">0,75×</option><option value="1">1×</option></select></label>
  </div>
 </section>;
}
