'use client';
import {useI18n} from './locale';
import {createContext,useContext,useEffect,useState} from 'react';
import type {Motion} from '@/lib/types';
import {staleOfflineIds} from '@/lib/offline-policy';
const CACHE='dosym-public-v1';
const Context=createContext<{saved:Motion[];save:(motion:Motion)=>Promise<void>;remove:(id:string)=>Promise<void>;clear:()=>Promise<void>}>({saved:[],save:async()=>{},remove:async()=>{},clear:async()=>{}});
export const useOffline=()=>useContext(Context);
async function database(){return new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open('dosym-public-motions',1);request.onupgradeneeded=()=>request.result.createObjectStore('motions',{keyPath:'id'});request.onerror=()=>reject(new Error('Браузер не разрешил локальное хранение.'));request.onsuccess=()=>resolve(request.result);});}
async function operation<T>(mode:IDBTransactionMode,work:(store:IDBObjectStore)=>IDBRequest<T>){const db=await database();try{return await new Promise<T>((resolve,reject)=>{const tx=db.transaction('motions',mode),req=work(tx.objectStore('motions'));let value:T;req.onsuccess=()=>{value=req.result;};tx.oncomplete=()=>resolve(value);tx.onerror=()=>reject(new Error('Не удалось сохранить данные. Проверьте свободное место.'));tx.onabort=()=>reject(new Error('Сохранение прервано.'));});}finally{db.close();}}
export function OfflineProvider({children}:{children:React.ReactNode}){const {t}=useI18n();
 const [saved,setSaved]=useState<Motion[]>([]),[waiting,setWaiting]=useState<ServiceWorker|null>(null);
 async function refresh(){setSaved(await operation('readonly',store=>store.getAll()) as Motion[]);}
 async function reconcile(){
  const local=await operation('readonly',store=>store.getAll()) as Motion[];
  if(navigator.onLine&&local.length){
   try{const response=await fetch('/api/gestures',{cache:'no-store'});if(!response.ok)throw new Error();const catalog=await response.json();
    for(const id of staleOfflineIds(local,catalog)){await operation('readwrite',store=>store.delete(id));if('caches'in window){const cache=await caches.open(CACHE);await cache.delete('/gestures/'+id);}}
   }catch{/* Failed connectivity is not proof of revocation. */}
  }
  await refresh();
 }
 useEffect(()=>{void reconcile().catch(()=>{});if('serviceWorker' in navigator){void navigator.serviceWorker.register('/sw.js').then(reg=>{if(reg.waiting&&navigator.serviceWorker.controller)setWaiting(reg.waiting);reg.addEventListener('updatefound',()=>{const worker=reg.installing;worker?.addEventListener('statechange',()=>{if(worker.state==='installed'&&navigator.serviceWorker.controller)setWaiting(worker);});});}).catch(()=>{});}const logout=()=>{void clear();};const connected=()=>{void reconcile().catch(()=>{});};window.addEventListener('online',connected);window.addEventListener('dosym-logout',logout);return()=>{window.removeEventListener('online',connected);window.removeEventListener('dosym-logout',logout);};},[]);
 async function save(motion:Motion){
  if(!('caches' in window)||!navigator.onLine)throw new Error('Для первого сохранения нужны сеть и поддержка хранилища браузером.');
  const cache=await caches.open(CACHE);const assetResponse=await fetch('/avatar/assets.json');if(!assetResponse.ok)throw new Error('Не удалось получить ресурсы аватара.');
  const assets=await assetResponse.json() as string[];
  assets.push('/offline.html','/offline.js','/offline-locales.js','/icons/icon.svg');
  for(const url of new Set(assets)){const cached=await cache.match(url);if(!cached){const response=await fetch(url);if(!response.ok)throw new Error('Не все ресурсы загрузились. Повторите сохранение.');await cache.put(url,response);}}
  await operation('readwrite',store=>store.put(motion));await refresh();
 }
 async function remove(id:string){await operation('readwrite',store=>store.delete(id));await refresh();}
 async function clear(){await operation('readwrite',store=>store.clear());setSaved([]);}
 return <Context.Provider value={{saved,save,remove,clear}}>{children}{waiting&&<div className="update-notice" role="status"><span>{t("Доступно обновление. Сначала завершите отправку и сохраните черновики.")}</span><button onClick={()=>{waiting.postMessage({type:'SKIP_WAITING'});navigator.serviceWorker.addEventListener('controllerchange',()=>location.reload(),{once:true});}}>{t("Обновить приложение")}</button><button onClick={()=>setWaiting(null)}>{t("Позже")}</button></div>}</Context.Provider>;
}
