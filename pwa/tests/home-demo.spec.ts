import {test,expect} from './fixtures';

test.use({serviceWorkers:'block',reducedMotion:'no-preference'});
test.beforeEach(async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:[{id:'fixture-motion',label:'сәлем',language:'kk-KZ',metadata:{}}]}));
 await page.route('**/gestures/fixture-motion/motion',route=>route.fulfill({headers:{'Access-Control-Allow-Origin':'*'},json:{id:'fixture-motion',label:'сәлем',sequence:[Array(162).fill(0.1)],fps:24,version:'fixture',metadata:{}}}));
 await page.route('**/avatar/index.html*',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><p id="received">No motion</p><script>addEventListener('message',e=>{if(e.source===parent&&e.data.type==='load-motion-queue')document.querySelector('#received').textContent=e.data.segments[0].label;});</script>`}));
});

test('home greets with a real sign without any user input',async({page})=>{
 await page.goto('/');
 await expect(page.locator('.player iframe')).toHaveCount(1);
 await expect(page.frameLocator('.player iframe').locator('#received')).toHaveText('сәлем',{timeout:5000});
});

test('reduced motion keeps the home page still',async({page})=>{
 await page.emulateMedia({reducedMotion:'reduce'});
 await page.goto('/');
 await expect(page.getByRole('button',{name:'сәлем',exact:true})).toBeVisible();
 await expect(page.locator('.player iframe')).toHaveCount(0);
});
