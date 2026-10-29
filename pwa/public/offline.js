(async()=>{
 let locale='kk';try{const saved=localStorage.getItem('dosym-locale');if(['kk','ru','en'].includes(saved))locale=saved;}catch{}
 const t=source=>locale==='ru'?source:(window.DOSYM_MESSAGES?.[source]?.[locale==='kk'?0:1]||source);
 const localize=()=>{document.documentElement.lang=locale;document.title=t('DosYm — сохранённые жесты');for(const node of document.querySelectorAll('[data-i18n]'))node.textContent=t(node.dataset.i18n);for(const anchor of document.querySelectorAll('[data-motion-label]'))anchor.textContent=anchor.dataset.motionLabel+' · '+t('Открыть жест');const selector=document.querySelector('#locale');selector.value=locale;selector.setAttribute('aria-label',t('Язык интерфейса'));document.querySelector('#avatar').title=t('Аватар DosYm');};
 document.querySelector('#locale').onchange=event=>{locale=event.target.value;try{localStorage.setItem('dosym-locale',locale);}catch{}localize();};
 localize();
 const open=()=>new Promise((resolve,reject)=>{const request=indexedDB.open('dosym-public-motions',1);request.onupgradeneeded=()=>request.result.createObjectStore('motions',{keyPath:'id'});request.onsuccess=()=>resolve(request.result);request.onerror=reject;});
 const query=async(mode,work)=>{const db=await open();try{return await new Promise((resolve,reject)=>{const tx=db.transaction('motions',mode),req=work(tx.objectStore('motions'));let result;req.onsuccess=()=>result=req.result;tx.oncomplete=()=>resolve(result);tx.onabort=reject;tx.onerror=reject;});}finally{db.close();}};
 try{
  const motions=await query('readonly',store=>store.getAll());
  const id=location.pathname.startsWith('/gestures/')?location.pathname.split('/')[2]:null;
  const motion=motions.find(item=>item.id===id);
  const list=document.querySelector('#list');
  if(motion){
   document.querySelector('#title').removeAttribute('data-i18n');document.querySelector('#title').textContent=motion.label;
   document.querySelector('#intro').dataset.i18n='Этот жест сохранён и доступен без подключения.';localize();
   document.querySelector('#viewer').hidden=false;
   const frame=document.querySelector('#avatar');
   const play=()=>frame.contentWindow.postMessage({type:'load-motion',sequence:motion.sequence,label:motion.label,fps:motion.fps,body_pose:motion.metadata.body_pose_landmarks,body_pose_world:motion.metadata.body_pose_world_landmarks,image_aspect_ratio:motion.metadata.image_aspect_ratio},location.origin);
   window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===frame.contentWindow&&event.data?.type==='avatar-ready')play();});
   frame.src='/avatar/index.html';document.querySelector('#play').onclick=play;
   document.querySelector('#remove').onclick=async()=>{await query('readwrite',store=>store.delete(id));location.href='/dictionary';};
  }else{
   if(!motions.length)document.querySelector('#empty').hidden=false;
   for(const item of motions){const anchor=document.createElement('a');anchor.href='/gestures/'+encodeURIComponent(item.id);anchor.dataset.motionLabel=item.label;anchor.textContent=item.label+' · '+t('Открыть жест');list.append(anchor);}
  }
 }catch{document.querySelector('#intro').dataset.i18n='Браузер не разрешил чтение офлайн-хранилища. Подключитесь к сети или проверьте настройки хранения.';localize();}
 window.addEventListener('online',()=>location.reload());
})();
