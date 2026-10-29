'use client';
import {useI18n} from './locale';
import {useEffect,useRef,useState} from 'react';
import {useRouter} from 'next/navigation';
import {useAuth} from './auth';
import {PageHeading} from './workspace';
import {Icon} from './icons';
import {api} from '@/lib/client';

type UploadInit={submission_id:string;upload_ticket:string;upload_origin:string;source_status:string};
export function Upload(){const {t,errorText}=useI18n();
 const {user,config}=useAuth(),router=useRouter();const input=useRef<HTMLInputElement>(null);
 const [file,setFile]=useState<File|null>(null),[preview,setPreview]=useState(''),[label,setLabel]=useState(''),[language,setLanguage]=useState('kk-KZ');
 const [rights,setRights]=useState(false),[training,setTraining]=useState(false),[research,setResearch]=useState(false),[step,setStep]=useState(1),[busy,setBusy]=useState(false),[progress,setProgress]=useState(0),[error,setError]=useState('');
 const [key,setKey]=useState('');
 useEffect(()=>{if(!file){setPreview('');return;}const url=URL.createObjectURL(file);setPreview(url);return()=>URL.revokeObjectURL(url);},[file]);
 function select(value:File|undefined){if(!value)return;setError('');if(value.size>100*1024*1024){setError('Выберите видео не больше 100 МБ.');return;}if(!/\.(mp4|webm|mov)$/i.test(value.name)){setError('Поддерживаются MP4, WebM и MOV.');return;}setFile(value);setKey(crypto.randomUUID());setProgress(0);setStep(1);}
 async function submit(){
  if(!file||!rights||!label.trim())return;setBusy(true);setError('');
  try{
   const mime=file.type||(/\.mov$/i.test(file.name)?'video/quicktime':/\.webm$/i.test(file.name)?'video/webm':'video/mp4');
   const upload=await api<UploadInit>('uploads/init',{method:'POST',body:JSON.stringify({label,language,filename:file.name,size:file.size,mime,rights,training,research,idempotency_key:key})});
   const origin=upload.upload_origin;const headers={Authorization:'Bearer '+upload.upload_ticket};
   // Upload endpoint is explicitly configured; do not send the user's Google token here.
   async function check(response:Response){if(!response.ok){const result=await response.json().catch(()=>({}));throw new Error(result.error||'Передача прервалась. Повторите отправку, чтобы продолжить.');}return response.json();}
   if(upload.source_status==='uploading'){
    const state=await check(await fetch(`${origin}/uploads/${upload.submission_id}/status`,{headers,cache:'no-store'}));
    let offset=state.received;setProgress(Math.round(offset/file.size*100));
    while(offset<file.size){const end=Math.min(offset+1024*1024,file.size);const response=await check(await fetch(`${origin}/uploads/${upload.submission_id}/chunks`,{method:'PUT',headers:{...headers,'Content-Type':'application/octet-stream','Content-Range':`bytes ${offset}-${end-1}/${file.size}`},body:file.slice(offset,end)}));offset=response.received;setProgress(Math.round(offset/file.size*100));}
    await check(await fetch(`${origin}/uploads/${upload.submission_id}/complete`,{method:'POST',headers}));
   }
   router.push('/materials/'+upload.submission_id);
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 return <><PageHeading title={t("Поделитесь одним жестом")} text={t("Короткая запись — ещё один шаг к общей библиотеке.")}/>
 <div className="upload-layout"><section className="upload-form"><ol className="steps" aria-label={t("Шаги загрузки")}>{[t("Видео"),t("Название и права"),t("Отправка")].map((s,i)=><li key={s} className={step===i+1?'current':step>i+1?'complete':''}><span>{step>i+1?<Icon name="check" size={15}/>:i+1}</span>{s}</li>)}</ol>
 {step===1&&<><h2>{t("Покажите жест целиком")}</h2><p className="muted">{t("Один жест в одном видео. До 60 секунд, 60 кадров/с, 100 МБ.")}</p><input ref={input} type="file" accept="video/mp4,video/webm,video/quicktime,.mov" className="sr-only" aria-label={t("Выберите видео")} onChange={e=>select(e.target.files?.[0])}/><button className="dropzone" onClick={()=>input.current?.click()} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();select(e.dataTransfer.files[0]);}}><Icon name="upload" size={34}/><strong>{file?file.name:t("Выберите видео или перетащите сюда")}</strong><span>{file?t("{0} МБ · Можно выбрать другое",{"0":(file.size/1024/1024).toFixed(1)}):t("MP4, WebM или MOV")}</span></button>{preview&&<video className="upload-preview" src={preview} controls playsInline preload="metadata"/>}<button className="button primary" disabled={!file} onClick={()=>setStep(2)}>{t("Продолжить")}<Icon name="arrow" size={18}/></button></>}
 {step===2&&<><h2>{t("Как называется жест?")}</h2><label className="field">{t("Слово, буква или короткая фраза")}<input value={label} maxLength={160} onChange={e=>setLabel(e.target.value)} placeholder={t("Например: Сәлем")}/></label><label className="field">{t("Язык метки")}<select value={language} onChange={e=>setLanguage(e.target.value)}><option value="kk-KZ">{t("Казахский")}</option><option value="ru-RU">{t("Русский")}</option></select></label><label className="check-field"><input type="checkbox" checked={rights} onChange={e=>setRights(e.target.checked)}/><span>{t("У меня есть право передать эту запись для обработки и показа жеста. Участники записи дали необходимое разрешение.")}</span></label><label className="check-field"><input type="checkbox" checked={training} onChange={e=>setTraining(e.target.checked)}/><span>{t("Разрешаю использовать запись и извлечённые координаты для обучения модели DosYm. Необязательно.")}</span></label><label className="check-field"><input type="checkbox" checked={research} onChange={e=>setResearch(e.target.checked)}/><span>{t("Разрешаю использовать запись и координаты в исследовательских проектах DosYm. Необязательно и отдельно от обучения.")}</span></label><div className="form-actions"><button className="button secondary" onClick={()=>setStep(1)}>{t("Назад")}</button><button className="button primary" disabled={!label.trim()||!rights} onClick={()=>setStep(3)}>{t("Проверить отправку")}<Icon name="arrow" size={18}/></button></div></>}
 {step===3&&<><h2>{t("Всё готово к отправке")}</h2><dl className="summary"><div><dt>{t("Жест")}</dt><dd>{label}</dd></div><div><dt>{t("Видео")}</dt><dd>{file?.name}</dd></div><div><dt>{t("Обучение")}</dt><dd>{training?t("Разрешено после проверки"):t("Не разрешено")}</dd></div><div><dt>{t("Исследования")}</dt><dd>{research?t("Разрешено"):t("Не разрешено")}</dd></div><div><dt>{t("Следующий шаг")}</dt><dd>{user?.role==='moderator'?t("Автоматическое извлечение координат"):t("Проверка модератором")}</dd></div></dl><p className="note">{t("Исходник сохраняется отдельно от координат. Автоматического удаления видео нет.")}</p>{config?.storage==='local'&&<p className="warning">{t("Локальная разработка: файл будет сохранён на этом компьютере. Google Диск пока не подключён.")}</p>}{busy&&<div className="progress-wrap" role="status"><progress max={100} value={progress}/><span>{progress===100?t("Видео передано. Проверяем формат…"):t("Передано {0}%",{"0":progress})}</span></div>}<div className="form-actions"><button className="button secondary" disabled={busy} onClick={()=>setStep(2)}>{t("Назад")}</button><button className="button primary" disabled={busy} onClick={submit}><Icon name="upload" size={18}/>{busy?t("Отправляем…"):error?t("Продолжить отправку"):t("Отправить видео")}</button></div></>}
 {error&&<p className="error" role="alert">{errorText(error)}</p>}
 </section><aside className="upload-guide"><span className="guide-symbol"><Icon name="hand" size={48}/></span><h2>{t("Чтобы жест был понятен")}</h2><ul><li>{t("Кисти, лицо и плечи остаются в кадре.")}</li><li>{t("Перед вами достаточно света, фон спокойный.")}</li><li>{t("Начните и завершите движение без спешки.")}</li><li>{t("Передавайте только записи, на которые у вас есть права.")}</li></ul><div className="guide-separator"/><h3>{t("Что произойдёт дальше")}</h3><p>{user?.role==='moderator'?t("Ваши записи проходят без отдельного одобрения. Проверка качества данных сохраняется."):t("Модератор проверит запись. После одобрения система извлечёт и сохранит координаты.")}</p><p className="small">{t("После завершения передачи обработка продолжается на сервере. Статус появится в «Моих материалах».")}</p></aside></div></>;
}
