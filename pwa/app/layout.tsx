import type { Metadata, Viewport } from 'next';
import { Manrope } from 'next/font/google';
import './globals.css';
const ui=Manrope({subsets:['latin','cyrillic','cyrillic-ext'],variable:'--font-ui',display:'swap'});
export const metadata:Metadata={title:'DosYm — ым кеңістігі',description:'Қазақ ым тілі: кітапхана, аватар және қауымдастық үлесі.',applicationName:'DosYm',appleWebApp:{capable:true,statusBarStyle:'default',title:'DosYm'},icons:{icon:'/icons/icon.svg',apple:'/icons/apple-touch-icon.png'}};
export const viewport:Viewport={width:'device-width',initialScale:1,themeColor:'#2454B8'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="kk" className={ui.variable} data-scroll-behavior="smooth"><body>{children}</body></html>;}
