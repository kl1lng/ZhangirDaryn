import {test,expect} from './fixtures';

test.use({serviceWorkers:'block'});
test.beforeEach(async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:['А','Ә','Сәлем'].map((label,i)=>({id:String(i),label,language:'kk-KZ',metadata:{}}))}));
});

test('install card appears only after the browser offers installation and can be dismissed for good',async({page})=>{
 await page.goto('/dictionary');
 await expect(page.getByRole('region',{name:'Установка приложения'})).toHaveCount(0);
 await page.evaluate(()=>{const e:any=new Event('beforeinstallprompt');e.prompt=async()=>{};e.userChoice=Promise.resolve({outcome:'dismissed'});window.dispatchEvent(e);});
 const card=page.getByRole('region',{name:'Установка приложения'});
 await expect(card).toBeVisible();
 await expect(card.getByRole('button',{name:'Установить',exact:true})).toBeVisible();
 await card.getByRole('button',{name:'Не сейчас'}).click();
 await expect(card).toHaveCount(0);
 await page.reload();
 await page.evaluate(()=>{const e:any=new Event('beforeinstallprompt');e.prompt=async()=>{};e.userChoice=Promise.resolve({outcome:'dismissed'});window.dispatchEvent(e);});
 await expect(page.getByRole('region',{name:'Установка приложения'})).toHaveCount(0);
});

test('dictionary offers to save the letters for offline use',async({page})=>{
 await page.goto('/dictionary');
 await expect(page.getByRole('button',{name:'Сохранить буквы для офлайн'})).toBeVisible();
});
