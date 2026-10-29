import type { SupabaseClient } from '@supabase/supabase-js';
let client:SupabaseClient|null=null;
let clientPromise:Promise<SupabaseClient|null>|null=null;
export class ApiError extends Error{constructor(message:string,public status:number){super(message);}}
export function supabaseConfigured(){return Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL&&process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);}
export async function supabase(){
  if(client)return client;
  if(!supabaseConfigured())return null;
  if(!clientPromise)clientPromise=import('@supabase/supabase-js').then(({createClient})=>{
    client=createClient(process.env.NEXT_PUBLIC_SUPABASE_URL!,process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,{auth:{flowType:'pkce',detectSessionInUrl:true}});return client;
  }).catch(error=>{clientPromise=null;throw error;});
  return clientPromise;
}
export async function token(){
  const local=sessionStorage.getItem('dosym-local-token');
  if(local)return local;
  const google=sessionStorage.getItem('dosym-google-session');
  if(google)return google;
  if(sessionStorage.getItem('dosym-auth-provider')!=='supabase')return '';
  const result=await (await supabase())?.auth.getSession();return result?.data.session?.access_token||'';
}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
  const publicMotion=/^gestures\/[a-zA-Z0-9_-]+\/motion$/.test(path);
  const auth=publicMotion||path==='auth/config'?'':await token();
  const direct=publicMotion||path==='auth/local'||auth.startsWith('local:');
  const endpoint=direct?(process.env.NEXT_PUBLIC_UPLOAD_ORIGIN||'http://127.0.0.1:8765')+'/'+path:'/api/'+path;
  const response=await fetch(endpoint,{...options,cache:'no-store',headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(auth?{Authorization:'Bearer '+auth}:{}),...options.headers}});
  if(!response.ok){let message='Не удалось выполнить действие.';try{const data=await response.json();message=data.error||data.detail?.[0]?.msg||message;}catch{}throw new ApiError(message,response.status);}
  return response.json();
}
export const statusText=(row:{source_status:string;moderation_status:string;processing_status:string})=>{
  if(row.source_status==='uploading')return 'Передача не завершена';
  if(row.moderation_status==='rejected')return 'Нужны изменения';
  if(row.moderation_status==='pending')return 'Ожидает проверки';
  return ({not_started:'Ожидает обработки',queued:'В очереди обработки',running:'Извлекаем координаты',ready:'Координаты сохранены',needs_video:'Нужно другое видео',failed:'Ошибка обработки'} as Record<string,string>)[row.processing_status]||row.processing_status;
};
