'use client';
import {createContext,useContext,useEffect,useMemo,useState} from 'react';
import {DEFAULT_LOCALE,LOCALE_STORAGE_KEY,isLocale,translate,translatedError,type Locale} from '@/lib/i18n';
const Context=createContext({locale:DEFAULT_LOCALE as Locale,setLocale:(_value:Locale)=>{},t:(source:string,values?:Record<string,string|number>)=>translate(source,DEFAULT_LOCALE,values),errorText:(source:string)=>translatedError(source,DEFAULT_LOCALE)});
export const useI18n=()=>useContext(Context);
export function LocaleProvider({children}:{children:React.ReactNode}){
 const [locale,update]=useState<Locale>(DEFAULT_LOCALE);
 useEffect(()=>{try{const saved=localStorage.getItem(LOCALE_STORAGE_KEY);if(isLocale(saved))update(saved);}catch{}},[]);
 useEffect(()=>{document.documentElement.lang=locale;document.title=locale==='kk'?'DosYm — ым кеңістігі':locale==='en'?'DosYm — space for signs':'DosYm — пространство жеста';},[locale]);
 const value=useMemo(()=>({locale,setLocale:(next:Locale)=>{if(!isLocale(next))return;update(next);try{localStorage.setItem(LOCALE_STORAGE_KEY,next);}catch{}},t:(source:string,values?:Record<string,string|number>)=>translate(source,locale,values),errorText:(source:string)=>translatedError(source,locale)}),[locale]);
 return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function LanguageSwitcher(){
 const {locale,setLocale,t}=useI18n();
 return <select className="language-switcher" aria-label={t('Язык интерфейса')} value={locale} onChange={e=>{if(isLocale(e.target.value))setLocale(e.target.value);}}><option value="kk" lang="kk">Қазақша</option><option value="ru" lang="ru">Русский</option><option value="en" lang="en">English</option></select>;
}
