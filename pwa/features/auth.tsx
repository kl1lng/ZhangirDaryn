'use client';
import { createContext,useContext,useEffect,useState } from 'react';
import { api,supabase } from '@/lib/client';
import type { User } from '@/lib/types';
type Config={auth_provider:'supabase'|'google';local_auth:boolean;google_configured:boolean;storage:string};
type Auth={user:User|null;loading:boolean;config:Config|null;refresh:()=>Promise<void>;logout:()=>Promise<void>};
const Context=createContext<Auth>({user:null,loading:true,config:null,refresh:async()=>{},logout:async()=>{}});
export const useAuth=()=>useContext(Context);
export function AuthProvider({children}:{children:React.ReactNode}){
 const [user,setUser]=useState<User|null>(null),[loading,setLoading]=useState(true),[config,setConfig]=useState<Config|null>(null);
 async function refresh(){try{setUser(await api<User>('me'));}catch{setUser(null);}finally{setLoading(false);}}
 useEffect(()=>{let cancelled=false;let subscription:{unsubscribe:()=>void}|undefined;void(async()=>{try{const next=await api<Config>('auth/config');if(cancelled)return;setConfig(next);sessionStorage.setItem('dosym-auth-provider',next.auth_provider);if(next.auth_provider==='supabase'){const auth=await supabase();if(cancelled)return;subscription=auth?.auth.onAuthStateChange(()=>{setTimeout(()=>void refresh(),0);}).data.subscription;}await refresh();}catch{if(!cancelled){setConfig(null);await refresh();}}})();return()=>{cancelled=true;subscription?.unsubscribe();};},[]);
 async function logout(){sessionStorage.removeItem('dosym-local-token');sessionStorage.removeItem('dosym-google-session');if(sessionStorage.getItem('dosym-auth-provider')==='supabase')await (await supabase())?.auth.signOut();setUser(null);window.dispatchEvent(new Event('dosym-logout'));}
 return <Context.Provider value={{user,loading,config,refresh,logout}}>{children}</Context.Provider>;
}
