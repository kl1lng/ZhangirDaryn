import {test,expect} from '@playwright/test';

test.use({serviceWorkers:'block'});

test.beforeEach(async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:[{id:'future-word',label:'Жаңа',language:'kk-KZ',metadata:{}}]}));
 await page.route('**/gestures/future-word/motion',route=>route.fulfill({headers:{'Access-Control-Allow-Origin':'*'},json:{id:'future-word',label:'Жаңа',sequence:[Array(162).fill(0.1)],fps:24,version:'fixture',metadata:{}}}));
 await page.route('**/avatar/index.html',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><p id="received"></p><script>addEventListener('message',e=>{if(e.source===parent&&e.data.type==='load-motion-queue')document.querySelector('#received').textContent=e.data.segments[0].label;});</script>`}));
});

test('Kazakh default, Russian and English switch preserves input and selected locale',async({page})=>{
 await page.goto('/');
 await expect(page.locator('html')).toHaveAttribute('lang','kk');
 await expect(page.getByRole('heading',{name:'Сөздер қимылға айналады'})).toBeVisible();
 await page.getByRole('textbox').fill('jaña');
 await page.getByRole('combobox',{name:'Интерфейс тілі'}).selectOption('ru');
 await expect(page.getByRole('heading',{name:'Слова становятся движением'})).toBeVisible();
 await expect(page.getByRole('textbox')).toHaveValue('jaña');
 await page.getByRole('combobox',{name:'Язык интерфейса'}).selectOption('en');
 await expect(page.getByRole('heading',{name:'Words become movement'})).toBeVisible();
 await page.reload();
 await expect(page.locator('html')).toHaveAttribute('lang','en');
 await expect(page.getByRole('heading',{name:'Words become movement'})).toBeVisible();
});

test('future catalog label plays from Latin text and is searchable in dictionary',async({page})=>{
 await page.goto('/');
 await expect(page.locator('.player iframe')).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Жаңа',exact:true})).toBeVisible();
 await page.getByRole('textbox').fill('zhanga');
 await page.getByRole('button',{name:'Ымды көрсету',exact:true}).click();
 await expect(page.locator('.player iframe')).toHaveCount(1);
 await expect(page.frameLocator('.player iframe').locator('#received')).toHaveText('Жаңа');
 await page.getByRole('link',{name:'Сөздік',exact:true}).first().click();
 await page.getByRole('textbox').fill('jaña');
 await expect(page.getByRole('heading',{name:'Жаңа',exact:true})).toBeVisible();
});

test('mobile language selector remains reachable and pages fit',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.goto('/login');
 await expect(page.getByRole('combobox',{name:'Интерфейс тілі'})).toBeVisible();
 await page.getByRole('combobox',{name:'Интерфейс тілі'}).selectOption('en');
 await expect(page.getByRole('button',{name:'Continue with Google'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('standalone offline shell uses the same default and language preference',async({page})=>{
 await page.goto('/offline.html');
 await expect(page.getByRole('heading',{name:'Желісіз сөздігіңіз'})).toBeVisible();
 await page.getByRole('combobox',{name:'Интерфейс тілі'}).selectOption('en');
 await expect(page.getByRole('heading',{name:'Your offline dictionary'})).toBeVisible();
 await page.reload();
 await expect(page.locator('html')).toHaveAttribute('lang','en');
});

test('upload permissions keep their values while switching language',async({page})=>{
 await page.route('**/api/me',route=>route.fulfill({json:{id:'fixture',email:'test@example.invalid',name:'Test',role:'moderator'}}));
 await page.goto('/upload');
 await page.getByLabel('Видео таңдаңыз',{exact:true}).setInputFiles('tests/fixtures/no-hands.mp4');
 await page.getByRole('button',{name:'Жалғастыру',exact:true}).click();
 await page.getByRole('textbox',{name:'Сөз, әріп немесе қысқа тіркес'}).fill('Жаңа');
 await page.getByRole('combobox',{name:'Интерфейс тілі'}).selectOption('en');
 await expect(page.getByRole('textbox',{name:'Word, letter or short phrase'})).toHaveValue('Жаңа');
 const permissions=page.getByRole('checkbox');
 await expect(permissions.nth(0)).not.toBeChecked();await expect(permissions.nth(1)).not.toBeChecked();await expect(permissions.nth(2)).not.toBeChecked();
 await expect(page.getByText('Research',{exact:true})).toHaveCount(0); // Still on the consent step.
 await permissions.nth(0).check();
 await page.getByRole('combobox',{name:'Interface language'}).selectOption('ru');
 await expect(permissions.nth(0)).toBeChecked();await expect(permissions.nth(1)).not.toBeChecked();
 await expect(page.getByRole('textbox',{name:'Слово, буква или короткая фраза'})).toHaveValue('Жаңа');
});

test('ambiguous ASCII asks for a choice before playing a sign',async({page})=>{
 const labels=[{id:'plain',label:'Ар',language:'kk-KZ',metadata:{}},{id:'diacritic',label:'Әр',language:'kk-KZ',metadata:{}}];
 await page.route('**/api/gestures',route=>route.fulfill({json:labels}));
 let requests=0;
 await page.route('**/gestures/diacritic/motion',route=>{requests++;return route.fulfill({headers:{'Access-Control-Allow-Origin':'*'},json:{...labels[1],sequence:[Array(162).fill(0.1)],fps:24,version:'fixture'}});});
 await page.goto('/');
 await expect(page.getByRole('button',{name:'Ар',exact:true})).toBeVisible();
 await page.getByRole('textbox').fill('ar');
 await page.getByRole('button',{name:'Ымды көрсету',exact:true}).click();
 const warning=page.getByRole('status').filter({hasText:'Ымды нақтылаңыз'});
 await expect(warning).toBeVisible();expect(requests).toBe(0);
 await warning.getByRole('button',{name:'Әр',exact:true}).click();
 await expect(page.frameLocator('.player iframe').locator('#received')).toHaveText('Әр');
 expect(requests).toBe(1);
});
