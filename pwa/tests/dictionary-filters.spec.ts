import {test,expect} from './fixtures';
test('dictionary combines type, alphabetic order and search',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('dosym-locale','ru'));
 await page.route('**/api/gestures',route=>route.fulfill({json:['Я','Ә','А','Сәлем','Автобус','Қайырлы таң'].map((label,i)=>({id:String(i),label,language:'kk-KZ',metadata:{}}))}));
 await page.goto('/dictionary');
 const cards=page.locator('.gesture-row h2');
 await expect(cards).toHaveText(['А','Автобус','Ә','Қайырлы таң','Сәлем','Я']);
 await page.getByLabel('Тип',{exact:true}).selectOption('letters');
 await expect(cards).toHaveText(['А','Ә','Я']);
 await page.getByLabel('Сортировка',{exact:true}).selectOption('desc');
 await expect(cards).toHaveText(['Я','Ә','А']);
 await page.getByLabel('Тип',{exact:true}).selectOption('words');
 await expect(cards).toHaveText(['Сәлем','Автобус']);
 await page.getByLabel('Поиск по словарю').fill('salem');
 await expect(cards).toHaveText(['Сәлем']);
 await page.getByLabel('Тип',{exact:true}).selectOption('phrases');
 await expect(cards).toHaveCount(0);
 await page.getByRole('button',{name:'Сбросить фильтры'}).click();
 await expect(cards).toHaveCount(6);
});

test('searching a missing word offers to record that sign',async({page})=>{
 await page.route('**/api/gestures',route=>route.fulfill({json:[{id:'1',label:'Сәлем',language:'kk-KZ',metadata:{}}]}));
 await page.goto('/dictionary');
 await page.getByRole('searchbox').or(page.locator('.search-field input')).first().fill('Рахмет');
 await expect(page.getByText('Жеста «Рахмет» пока нет')).toBeVisible();
 await expect(page.getByRole('link',{name:'Записать этот жест'})).toHaveAttribute('href','/upload');
});

test('typing shows word suggestions that complete the current word',async({page})=>{
 await page.route('**/api/gestures',route=>route.fulfill({json:['Сәлем','Автобус','Күн'].map((label,i)=>({id:String(i),label,language:'kk-KZ',metadata:{}}))}));
 await page.goto('/');
 await page.getByLabel('Текст для показа жестами').fill('Мен Сәл');
 await page.getByRole('group',{name:'Подсказки слов'}).getByRole('button',{name:'Сәлем'}).click();
 await expect(page.getByLabel('Текст для показа жестами')).toHaveValue('Мен Сәлем ');
});
