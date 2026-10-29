import {messages} from './messages.ts';
export type Locale='kk'|'ru'|'en';
export const DEFAULT_LOCALE:Locale='kk';
export const LOCALE_STORAGE_KEY='dosym-locale';
export const isLocale=(value:unknown):value is Locale=>value==='kk'||value==='ru'||value==='en';
export function translate(source:string,locale:Locale=DEFAULT_LOCALE,values:Record<string,string|number>={}){
 const key=source.replace(/\s+/g,' ').trim();
 const pair=messages[key];
 let value=locale==='ru'||!pair?source:(/^\s/.test(source)?' ':'')+pair[locale==='kk'?0:1]+(/\s$/.test(source)?' ':'');
 value=value.replace(/\{(\w+)\}/g,(whole,name)=>name in values?String(values[name]):whole);
 return value;
}
export function translatedError(message:string,locale:Locale){
 return locale==='ru'||messages[message.replace(/\s+/g,' ').trim()]?translate(message,locale):translate('Не удалось выполнить действие.',locale);
}
