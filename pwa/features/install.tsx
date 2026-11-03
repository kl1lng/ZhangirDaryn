'use client';
import {useEffect,useState} from 'react';
import {useI18n} from './locale';
import {Icon} from './icons';

type InstallPrompt=Event&{prompt:()=>Promise<void>;userChoice:Promise<{outcome:'accepted'|'dismissed'}>};
const DISMISSED='dosym-install-dismissed';
const read=()=>{try{return localStorage.getItem(DISMISSED)==='1';}catch{return false;}};
const write=()=>{try{localStorage.setItem(DISMISSED,'1');}catch{/* private mode */}};

// Offers installation where the browser supports it, and explains the manual route on iPhone/iPad.
export function InstallPrompt(){const {t}=useI18n();
 const [event,setEvent]=useState<InstallPrompt|null>(null),[ios,setIos]=useState(false),[hidden,setHidden]=useState(true);
 useEffect(()=>{
  const standalone=window.matchMedia('(display-mode: standalone)').matches||(navigator as Navigator&{standalone?:boolean}).standalone===true;
  if(standalone||read())return;
  const apple=/iPad|iPhone|iPod/.test(navigator.userAgent)&&!/CriOS|FxiOS|EdgiOS/.test(navigator.userAgent);
  setIos(apple);setHidden(!apple);
  const before=(e:Event)=>{e.preventDefault();setEvent(e as InstallPrompt);setHidden(false);};
  const installed=()=>{setEvent(null);setHidden(true);write();};
  window.addEventListener('beforeinstallprompt',before);window.addEventListener('appinstalled',installed);
  return()=>{window.removeEventListener('beforeinstallprompt',before);window.removeEventListener('appinstalled',installed);};
 },[]);
 if(hidden||(!event&&!ios))return null;
 const dismiss=()=>{write();setHidden(true);};
 return <div className="install-card" role="region" aria-label={t("Установка приложения")}>
  <div className="install-text"><strong>{t("Установить DosYm")}</strong><span>{event?t("Откроется как приложение и будет работать без сети для сохранённых жестов."):t("Нажмите «Поделиться», затем «На экран Домой».")}</span></div>
  <div className="install-actions">{event&&<button type="button" className="button primary" onClick={async()=>{await event.prompt();const choice=await event.userChoice;setEvent(null);if(choice.outcome==='accepted'){write();setHidden(true);}}}><Icon name="download" size={18}/>{t("Установить")}</button>}<button type="button" className="install-dismiss" onClick={dismiss}>{t("Не сейчас")}</button></div>
 </div>;
}
