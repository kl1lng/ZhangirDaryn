import type { Metadata, Viewport } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
const ui=Inter({subsets:['latin','cyrillic','cyrillic-ext'],variable:'--font-ui',display:'swap'});
export const metadata:Metadata={metadataBase:new URL(process.env.NEXT_PUBLIC_SITE_URL||'https://dosym-seven.vercel.app'),openGraph:{type:'website',siteName:'DosYm',title:'DosYm — ым кеңістігі',description:'Қазақ ым тілі: кітапхана, аватар және қауымдастық үлесі.',images:[{url:'/icons/logo-mark.png',width:512,height:512,alt:'DosYm'}]},twitter:{card:'summary',title:'DosYm — ым кеңістігі',description:'Қазақ ым тілі: кітапхана, аватар және қауымдастық үлесі.',images:['/icons/logo-mark.png']},title:'DosYm — ым кеңістігі',description:'Қазақ ым тілі: кітапхана, аватар және қауымдастық үлесі.',applicationName:'DosYm',appleWebApp:{capable:true,statusBarStyle:'default',title:'DosYm'},icons:{icon:'/icons/favicon-64.png',apple:'/icons/apple-touch-icon.png'}};
export const viewport:Viewport={width:'device-width',initialScale:1,themeColor:'#2454B8'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="kk" className={ui.variable} data-scroll-behavior="smooth" suppressHydrationWarning><body suppressHydrationWarning>{children}</body></html>;}
