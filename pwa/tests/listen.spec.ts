import {test,expect} from './fixtures';

test.use({serviceWorkers:'block',reducedMotion:'reduce'});
const library=['Су','Ана','Бала','Дос','М','Е','Н'].map((label,i)=>({id:`g${i}`,label,language:'kk-KZ',metadata:{}}));
const motion=(id:string,label:string)=>({id:id,label,sequence:[Array(162).fill(0.1)],fps:24,version:'fixture',metadata:{}});

test.beforeEach(async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:library}));
 for(const row of library)await page.route(`**/gestures/${row.id}/motion`,route=>route.fulfill({headers:{'Access-Control-Allow-Origin':'*'},json:motion(row.id,row.label)}));
 // The stub avatar reports the labels it received and never finishes by itself: the test ends each phrase.
 await page.route('**/avatar/index.html*',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><p id="received">No motion</p><script>addEventListener('message',e=>{if(e.source===parent&&e.data.type==='load-motion-queue')document.querySelector('#received').textContent=e.data.segments.map(s=>s.label).join(',');});window.finish=()=>parent.postMessage({type:'motion-ended'},location.origin);</script>`}));
 await page.addInitScript(()=>{
  localStorage.setItem('dosym-locale','ru');
  class FakeRecognition{
   lang='';interimResults=false;continuous=false;onstart:Function|null=null;onresult:Function|null=null;onerror:Function|null=null;onend:Function|null=null;
   start(){(window as any).speechInstance=this;(window as any).speechStarts=((window as any).speechStarts||0)+1;this.onstart?.();}
   stop(){this.onend?.();}
   abort(){(window as any).speechAborted=true;}
  }
  (window as any).SpeechRecognition=FakeRecognition;
  (window as any).say=(texts:string[])=>{const results=texts.map(text=>Object.assign([{transcript:text}],{isFinal:true}));(window as any).speechInstance.onresult({resultIndex:0,results});};
 });
});

const received=(page:any)=>page.frameLocator('.player iframe').locator('#received');
const finishPhrase=(page:any)=>page.frameLocator('.player iframe').locator('body').evaluate(()=>(window as any).finish());

test('listening is continuous: a phrase plays, the next one waits and starts when the first ends',async({page})=>{
 await page.goto('/listen');
 await page.getByRole('button',{name:'Начать слушать'}).click();
 expect(await page.evaluate(()=>(window as any).speechInstance.continuous)).toBe(true);
 await page.evaluate(()=>(window as any).say(['ана бала']));
 await expect(received(page)).toHaveText('Ана,Бала',{timeout:8000});
 await page.evaluate(()=>{const w=window as any;w.speechInstance.onresult({resultIndex:1,results:['ана бала','дос'].map(text=>Object.assign([{transcript:text}],{isFinal:true}))});});
 await expect(page.locator('.line-waiting')).toHaveCount(1);
 await finishPhrase(page);
 await expect(received(page)).toHaveText('Дос',{timeout:8000});
 await expect(page.locator('.line-done')).toHaveCount(1);
});

test('unknown words are spelled and the page says so; recognition restarts by itself after the browser ends it',async({page})=>{
 await page.goto('/listen');
 await page.getByRole('button',{name:'Начать слушать'}).click();
 await page.evaluate(()=>(window as any).say(['мен су']));
 await expect(received(page)).toHaveText('М,Е,Н,Су',{timeout:8000});
 await expect(page.getByText('по буквам: мен')).toBeVisible();
 await page.evaluate(()=>(window as any).speechInstance.onend());
 await expect.poll(()=>page.evaluate(()=>(window as any).speechStarts)).toBeGreaterThan(1);
 await expect(page.getByRole('button',{name:'Остановить прослушивание'})).toBeVisible();
});

test('speech faster than the avatar skips the oldest waiting phrases and says how many',async({page})=>{
 await page.goto('/listen');
 await page.getByRole('button',{name:'Начать слушать'}).click();
 await page.evaluate(()=>(window as any).say(['су']));
 await expect(received(page)).toHaveText('Су',{timeout:8000});
 await page.evaluate(()=>{const w=window as any;w.speechInstance.onresult({resultIndex:1,results:['су','ана','бала','дос','су','ана'].map(text=>Object.assign([{transcript:text}],{isFinal:true}))});});
 await expect(page.getByText(/пропущено фраз: 2/i)).toBeVisible();
 await expect(page.locator('.line-skipped')).toHaveCount(2);
});

test('stopping releases the microphone; unsupported browsers get an explanation',async({page})=>{
 await page.goto('/listen');
 await page.getByRole('button',{name:'Начать слушать'}).click();
 await page.getByRole('button',{name:'Остановить прослушивание'}).click();
 await expect(page.getByRole('button',{name:'Начать слушать'})).toBeVisible();
 await page.addInitScript(()=>{delete (window as any).SpeechRecognition;delete (window as any).webkitSpeechRecognition;});
 await page.reload();
 await expect(page.getByRole('button',{name:'Начать слушать'})).toBeDisabled();
 await expect(page.getByText('Голосовой ввод недоступен в этом браузере.')).toBeVisible();
});
