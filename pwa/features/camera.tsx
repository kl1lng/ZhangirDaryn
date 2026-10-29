'use client';
import Link from 'next/link';
import {useCallback,useEffect,useRef,useState} from 'react';
import {useI18n} from './locale';
import {Icon} from './icons';
import type {CameraCandidate} from '@/lib/camera-match';

const CONNECTIONS=[[0,1],[1,2],[2,3],[3,4],[0,5],[5,6],[6,7],[7,8],[5,9],[9,10],[10,11],[11,12],[9,13],[13,14],[14,15],[15,16],[13,17],[17,18],[18,19],[19,20],[0,17]];
export function Camera(){
 const {t}=useI18n();
 const [phase,setPhase]=useState('idle'),[error,setError]=useState(''),[hands,setHands]=useState(0),[collecting,setCollecting]=useState(true),[candidates,setCandidates]=useState<CameraCandidate[]>([]),[facing,setFacing]=useState('user');
 const video=useRef<HTMLVideoElement>(null),canvas=useRef<HTMLCanvasElement>(null),worker=useRef<Worker|null>(null),stream=useRef<MediaStream|null>(null),timer=useRef<ReturnType<typeof setTimeout>|null>(null),watchdog=useRef<ReturnType<typeof setTimeout>|null>(null),generation=useRef(0);
 const stop=useCallback((update=true)=>{
  generation.current++;if(timer.current)clearTimeout(timer.current);if(watchdog.current)clearTimeout(watchdog.current);timer.current=null;watchdog.current=null;
  const running=worker.current;worker.current=null;if(running){running.onmessage=null;running.onerror=null;running.terminate();}
  stream.current?.getTracks().forEach(track=>track.stop());stream.current=null;
  if(video.current)video.current.srcObject=null;
  if(canvas.current)canvas.current.getContext('2d')?.clearRect(0,0,canvas.current.width,canvas.current.height);
  if(update){setPhase('idle');setCandidates([]);setHands(0);setCollecting(true);}
 },[]);
 useEffect(()=>{const hidden=()=>{if(document.hidden)stop();};document.addEventListener('visibilitychange',hidden);return()=>{document.removeEventListener('visibilitychange',hidden);stop(false);};},[stop]);
 function fail(message:string){stop();setError(message);}
 function draw(landmarks:{x:number;y:number}[][]){
  const target=canvas.current,source=video.current;if(!target||!source)return;
  target.width=source.videoWidth||640;target.height=source.videoHeight||480;
  const context=target.getContext('2d');if(!context)return;context.clearRect(0,0,target.width,target.height);context.strokeStyle='#38c8b4';context.fillStyle='#fff';context.lineWidth=3;
  for(const hand of landmarks){for(const [a,b] of CONNECTIONS){if(!hand[a]||!hand[b])continue;context.beginPath();context.moveTo(hand[a].x*target.width,hand[a].y*target.height);context.lineTo(hand[b].x*target.width,hand[b].y*target.height);context.stroke();}for(const point of hand){context.beginPath();context.arc(point.x*target.width,point.y*target.height,3,0,Math.PI*2);context.fill();}}
 }
 function start(){
  stop();setError('');
  if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia||!window.Worker||!window.createImageBitmap||!window.OffscreenCanvas){setError('Камера недоступна в этом браузере. Используйте современный браузер с HTTPS.');return;}
  const library=process.env.NEXT_PUBLIC_LIBRARY_URL;
  if(!library){setError('Библиотека для камеры ещё не подключена.');return;}
  const session=generation.current;
  setPhase('model');
  let engine:Worker;
  try{engine=new Worker('/camera/worker.js');worker.current=engine;}catch{fail('Не удалось запустить обработку камеры. Попробуйте другой браузер.');return;}
  const current=()=>generation.current===session&&worker.current===engine;
  const capture=async()=>{
   if(!current())return;
   const source=video.current;
   if(!source||source.readyState<2||!source.videoWidth){timer.current=setTimeout(capture,100);return;}
   try{
    const width=Math.min(640,source.videoWidth),height=Math.round(width*source.videoHeight/source.videoWidth);
    const bitmap=await createImageBitmap(source,{resizeWidth:width,resizeHeight:height});
    if(!current()){bitmap.close();return;}
    watchdog.current=setTimeout(()=>{if(current())fail('Обработка камеры остановилась. Попробуйте включить её снова.');},15000);
    try{engine.postMessage({type:'frame',bitmap,timestamp:performance.now()},[bitmap]);}catch{bitmap.close();throw new Error('Frame transfer failed');}
   }catch{if(current())fail('Не удалось прочитать изображение камеры. Попробуйте включить её снова.');}
  };
  engine.onmessage=async({data})=>{
   if(!current())return;
   if(data.type==='progress'){setPhase(data.stage);return;}
   if(data.type==='error'){fail(data.code==='initialization'?'Не удалось загрузить модель или библиотеку. Проверьте сеть и повторите.':'Не удалось обработать кадр камеры. Попробуйте включить её снова.');return;}
   if(data.type==='ready'){
    if(watchdog.current)clearTimeout(watchdog.current);setPhase('permission');
    try{
     const acquired=await navigator.mediaDevices.getUserMedia({audio:false,video:{facingMode:{ideal:facing},width:{ideal:640},height:{ideal:480},frameRate:{ideal:15,max:24}}});
     if(!current()){acquired.getTracks().forEach(track=>track.stop());return;}
     stream.current=acquired;const source=video.current;if(!source)throw new Error('No video element');source.srcObject=acquired;
     for(const track of acquired.getTracks())track.onended=()=>{if(current())fail('Камера отключена. Подключите её и попробуйте снова.');};
     await source.play();if(!current())return;setPhase('running');void capture();
    }catch(reason){if(!current())return;const name=(reason as Error).name;fail(name==='NotAllowedError'?'Разрешите доступ к камере в настройках браузера.':name==='NotFoundError'?'Камера не найдена. Подключите камеру и повторите.':'Не удалось открыть камеру. Возможно, она занята другим приложением.');}
   }
   if(data.type==='result'){
    if(watchdog.current)clearTimeout(watchdog.current);setHands(data.hands);setCollecting(data.collecting);
    setCandidates(previous=>JSON.stringify(previous.map(item=>item.id))===JSON.stringify(data.candidates.map((item:CameraCandidate)=>item.id))?previous:data.candidates);
    draw(data.landmarks);timer.current=setTimeout(capture,100);
   }
  };
  engine.onerror=()=>{if(current())fail('Не удалось запустить обработку камеры. Попробуйте другой браузер.');};
  watchdog.current=setTimeout(()=>{if(current())fail('Не удалось загрузить модель или библиотеку. Проверьте сеть и повторите.');},90000);
  engine.postMessage({type:'init',referenceUrl:library.replace(/\/$/,'')+'/camera.json'});
 }
 const active=phase!=='idle';
 const status=phase==='model'?'Загружаем модель кистей…':phase==='references'?'Подготавливаем примеры жестов…':phase==='permission'?'Разрешите доступ к камере в окне браузера.':phase==='running'?(hands===0?'Руки не видны в кадре.':collecting?'Покажите жест: собираем движение…':candidates.length?'Похожие примеры найдены.':'Жест не определён.'):'Камера выключена.';
 return <><div className="page-heading"><div><h1>{t('Камера: жесты в текст')}</h1><p>{t('Экспериментальное сравнение с примерами библиотеки.')}</p></div><span className="section-tag">{t('Эксперимент')}</span></div>
  <section className="camera-panel">
   <p className="camera-instructions">{t('Сядьте по центру, держите кисти целиком в кадре и покажите один жест. Мимика в этом режиме не учитывается.')}</p>
   <div className={'camera-preview '+(facing==='user'?'camera-mirrored':'')}><video ref={video} muted playsInline aria-label={t('Изображение с вашей камеры')}/><canvas ref={canvas} aria-hidden="true"/>{phase!=='running'&&<div className="camera-placeholder"><Icon name="camera" size={40}/><span>{t(status)}</span></div>}</div>
   <div className="camera-controls"><button type="button" className={'button '+(active?'secondary':'primary')} onClick={()=>active?stop():start()}><Icon name="camera" size={18}/>{active?t('Остановить камеру'):t('Включить камеру')}</button><label>{t('Камера')}<select value={facing} disabled={active} onChange={event=>setFacing(event.target.value)}><option value="user">{t('Передняя')}</option><option value="environment">{t('Задняя')}</option></select></label></div>
   <div className="camera-results" role="status" aria-live="polite"><h2>{t('Похожие примеры')}</h2><p>{t(status)}</p>{candidates.length>0&&<ul>{candidates.map(candidate=><li key={candidate.id}><Link href={'/gestures/'+candidate.id}>{candidate.label}</Link></li>)}</ul>}</div>
   {error&&<p className="error" role="alert">{t(error)}</p>}
   <p className="camera-privacy">{t('Видео не записывается и не отправляется на сервер. При скрытии вкладки камера останавливается. Модель и примеры загружаются при включении.')}</p>
   <p className="camera-privacy">{t('Показаны похожие образцы, а не подтверждённый перевод. Проверьте результат по демонстрации жеста в словаре.')}</p>
  </section></>;
}
