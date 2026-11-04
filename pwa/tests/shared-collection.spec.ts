import {test,expect} from './fixtures';

test.use({serviceWorkers:'block',reducedMotion:'reduce'});
const own=[{id:'own-1',label:'Сәлем',language:'kk-KZ',metadata:{}}];
const shared=[
 {id:'rsl-aaa',label:'Су',language:'kk-KZ',sign_language:'rsl',review:'pending',aliases:['вода'],metadata:{}},
 {id:'rsl-bbb',label:'Көмектесу',language:'kk-KZ',sign_language:'rsl',review:'pending',aliases:['помочь'],metadata:{}},
 {id:'rsl-ccc',label:'сүт',language:'kk-KZ',sign_language:'rsl',review:'pending',aliases:['молоко'],metadata:{}},
];
const motion=(id:string,label:string)=>({id,label,sequence:[Array(162).fill(0.1)],fps:24,version:'fixture',metadata:{}});

test.beforeEach(async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:own}));
 await page.route('**/rsl/catalog.json',route=>route.fulfill({json:shared}));
 for(const row of shared)await page.route(`**/rsl/${row.id}.json`,route=>route.fulfill({headers:{'Access-Control-Allow-Origin':'*'},json:motion(row.id,row.label)}));
 await page.route('**/avatar/index.html*',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><p id="received">No motion</p><script>addEventListener('message',e=>{if(e.source===parent&&e.data.type==='load-motion-queue')document.querySelector('#received').textContent=e.data.segments.map(s=>s.label).join(',');});</script>`}));
});

test('translator plays shared words from Kazakh text and from the Russian original, and there is no language notice',async({page})=>{
 await page.goto('/');
 const input=page.getByLabel('Текст для показа жестами');
 await input.fill('Су');
 await page.getByRole('button',{name:'Показать жесты',exact:true}).click();
 await expect(page.frameLocator('.player iframe').locator('#received')).toHaveText('Су',{timeout:8000});
 await input.fill('помочь вода');
 await page.getByRole('button',{name:'Показать жесты',exact:true}).click();
 await expect(page.frameLocator('.player iframe').locator('#received')).toHaveText('Көмектесу,Су',{timeout:8000});
 await expect(page.getByRole('note')).toHaveCount(0);
});

test('dictionary lists shared words with capital initials, one filter letter per letter and no language switch',async({page})=>{
 await page.goto('/dictionary');
 await expect(page.locator('.gesture-row h2')).toHaveText(['Көмектесу','Сәлем','Су','Сүт']);
 await expect(page.getByLabel('Ым тілі')).toHaveCount(0);
 const letters=(await page.locator('.alphabet-filter button').allTextContents()).filter(text=>text.length===1);
 expect(letters.filter(letter=>letter==='С')).toHaveLength(1);
 expect(letters.some(letter=>letter!==letter.toUpperCase())).toBe(false);
 await page.getByRole('searchbox').or(page.locator('.search-field input')).first().fill('молоко');
 await expect(page.locator('.gesture-row h2')).toHaveText(['Сүт']);
 await expect(page.getByText(/не казахский|Орыс ым тілі/)).toHaveCount(0);
});
