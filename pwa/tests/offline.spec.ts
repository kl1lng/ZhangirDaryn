import {test,expect} from '@playwright/test';

test.beforeEach(async({page})=>{await page.addInitScript(()=>localStorage.setItem('dosym-locale','ru'));});
test('explicitly downloaded public motion opens without a network',async({page,context})=>{
 const motion={id:'offline-fixture',label:'Офлайн-проверка',sequence:Array.from({length:3},()=>Array(162).fill(0.1)),fps:30,metadata:{},version:'fixture-v1'};
 await page.route('**/api/gestures',route=>route.fulfill({json:[{id:motion.id,label:motion.label,language:'kk-KZ',metadata:{},version:motion.version}]}));
 await page.route('**/gestures/offline-fixture/motion',route=>route.fulfill({json:motion}));
 await page.goto('/gestures/offline-fixture');
 await expect(page.getByRole('heading',{name:motion.label,exact:true})).toBeVisible();
 await page.evaluate(()=>navigator.serviceWorker.ready);
 await page.getByRole('button',{name:'Сохранить для офлайн'}).click();
 await expect(page.getByRole('button',{name:'Убрать из офлайн'})).toBeVisible({timeout:30000});
 await context.setOffline(true);
 await page.goto('/gestures/offline-fixture');
 await expect(page.getByRole('heading',{name:motion.label,exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Убрать из офлайн'})).toBeVisible();
 await context.setOffline(false);
});
