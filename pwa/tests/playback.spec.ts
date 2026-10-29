import {test,expect} from '@playwright/test';

test.use({serviceWorkers:'block'});
test.beforeEach(async({page})=>{await page.addInitScript(()=>localStorage.setItem('dosym-locale','ru'));});

test('player loads the avatar only after a gesture is chosen and sends motion without the ready message',async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:[{id:'fixture-motion',label:'сәлем',language:'kk-KZ',metadata:{}}]}));
 await page.route('**/gestures/fixture-motion/motion',route=>route.fulfill({headers:{'Access-Control-Allow-Origin':'*'},json:{id:'fixture-motion',label:'сәлем',sequence:[Array(162).fill(0.1)],fps:24,version:'fixture',metadata:{}}}));
 await page.route('**/avatar/index.html',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><p id="received">No motion</p><script>addEventListener('message',e=>{if(e.source===parent&&e.data.type==='load-motion-queue')document.querySelector('#received').textContent=e.data.segments[0].label;});</script>`}));
 await page.goto('/');
 await expect(page.locator('.player iframe')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'сәлем',exact:true})).toBeVisible();
 await page.getByLabel('Текст для показа жестами').fill('Сәлем');
 await page.getByRole('button',{name:'Показать жесты',exact:true}).click();
 await expect(page.locator('.player iframe')).toHaveCount(1);
 await expect(page.frameLocator('.player iframe').locator('#received')).toHaveText('сәлем',{timeout:5000});
 await expect(page.getByRole('button',{name:'Приостановить',exact:true})).toBeEnabled();
});

test('player pauses offscreen and does not auto-resume when it becomes visible',async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:[{id:'fixture-motion',label:'сәлем',language:'kk-KZ',metadata:{}}]}));
 await page.route('**/gestures/fixture-motion/motion',route=>route.fulfill({headers:{'Access-Control-Allow-Origin':'*'},json:{id:'fixture-motion',label:'сәлем',sequence:[Array(162).fill(0.1)],fps:24,version:'fixture',metadata:{}}}));
 await page.route('**/avatar/index.html',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><p id="visibility">unknown</p><p id="playback">ready</p><script>
 addEventListener('message',event=>{if(event.source!==parent)return;
 if(event.data.type==='visibility')document.querySelector('#visibility').textContent=event.data.visible?'visible':'hidden';
 if(event.data.type==='load-motion-queue')document.querySelector('#playback').textContent='playing';
 if(event.data.type==='pause')document.querySelector('#playback').textContent='paused';
 if(event.data.type==='resume')document.querySelector('#playback').textContent='resumed';});
 parent.postMessage({type:'avatar-ready'},location.origin);
 </script>`}));
 await page.goto('/');
 const frame=page.locator('.player iframe');
 await expect(page.getByRole('button',{name:'сәлем',exact:true})).toBeVisible();
 await page.getByLabel('Текст для показа жестами').fill('Сәлем');
 await page.getByRole('button',{name:'Показать жесты',exact:true}).click();
 await expect(page.getByRole('button',{name:'Приостановить',exact:true})).toBeEnabled();
 await frame.evaluate(element=>{element.style.position='fixed';element.style.top='-2000px'});
 await expect(page.getByRole('button',{name:'Продолжить',exact:true})).toBeVisible();
 await expect(page.frameLocator('.player iframe').locator('#playback')).toHaveText('paused');
 await frame.evaluate(element=>{element.style.position='';element.style.top=''});
 await expect(page.frameLocator('.player iframe').locator('#visibility')).toHaveText('visible');
 await page.getByRole('button',{name:'Продолжить',exact:true}).click();
 await expect(page.getByRole('button',{name:'Приостановить',exact:true})).toBeVisible();
 await expect(page.frameLocator('.player iframe').locator('#playback')).toHaveText('resumed');
});
