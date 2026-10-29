export function Icon({name,size=22}:{name:string;size?:number}){
 const shapes:Record<string,React.ReactNode>={
  translate:<><path d="M4 5h12M10 3v2M6 8c1 4 4 7 8 9M14 5c-1 6-4 10-10 13M14 21l4-10 4 10M16 17h4"/></>,
  book:<><path d="M3 4h7a3 3 0 0 1 3 3v14a4 4 0 0 0-4-2H3zM13 7a3 3 0 0 1 3-3h5v15h-5a4 4 0 0 0-3 2"/></>,
  add:<><path d="M12 5v14M5 12h14"/></>,
  folder:<path d="M3 7V5h6l2 3h10v12H3z"/>,
  shield:<><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/></>,
  settings:<><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/></>,
  play:<path d="m9 5 11 7-11 7z"/>,pause:<><path d="M8 5v14M16 5v14"/></>,
  search:<><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  mic:<><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></>,
  camera:<><path d="M3 6h4l2-3h6l2 3h4v15H3z"/><circle cx="12" cy="13" r="4"/></>,
  upload:<><path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/></>,
  arrow:<><path d="M4 12h15m-5-5 5 5-5 5"/></>,
  check:<path d="m5 12 4 4L19 6"/>,
  download:<><path d="M12 3v13m-5-5 5 5 5-5M4 18v3h16v-3"/></>,
  model:<><path d="m12 2 9 5v10l-9 5-9-5V7zM3 7l9 5 9-5M12 12v10"/></>,
  hand:<><path d="M8 12V6a1.5 1.5 0 0 1 3 0v5-7a1.5 1.5 0 0 1 3 0v7-6a1.5 1.5 0 0 1 3 0v7-4a1.5 1.5 0 0 1 3 0v8c0 4-3 6-7 6-3 0-5-2-6-4l-3-5c-1-2 1-3 2-1l2 2"/></>,
 };
 return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{shapes[name]||shapes.hand}</svg>;
}
