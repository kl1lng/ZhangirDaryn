import {test,expect} from '@playwright/test';

test.beforeEach(async({page})=>{await page.addInitScript(()=>localStorage.setItem('dosym-locale','ru'));});
import path from 'node:path';

test('a real video waits for moderation, then extraction failure preserves its source',async({page})=>{
 const label='Техническая проверка '+Date.now();
 await page.goto('/login?next=/upload');
 await page.getByRole('button',{name:'Проверить как участник'}).click();
 await page.getByLabel('Выберите видео').setInputFiles(path.resolve('tests/fixtures/no-hands.mp4'));
 await page.getByRole('button',{name:'Продолжить',exact:true}).click();
 await page.getByLabel('Слово, буква или короткая фраза').fill(label);
 await page.getByLabel('У меня есть право передать эту запись',{exact:false}).check();
 await page.getByLabel('Разрешаю использовать запись и координаты в исследовательских проектах DosYm',{exact:false}).check();
 await expect(page.getByLabel('Разрешаю использовать запись и извлечённые координаты для обучения модели DosYm',{exact:false})).not.toBeChecked();
 await page.getByRole('button',{name:'Проверить отправку'}).click();
 await expect(page.getByText('Исследования',{exact:true}).locator('..')).toContainText('Разрешено');
 await expect(page.getByText('Обучение',{exact:true}).locator('..')).toContainText('Не разрешено');
 await page.getByRole('button',{name:'Отправить видео',exact:true}).click();
 await expect(page).toHaveURL(/\/materials\//);
 const url=page.url();
 await expect(page.getByText('Ожидает проверки',{exact:true}).first()).toBeVisible();
 const video=page.locator('video');
 await expect(video).toHaveAttribute('src',/^http:\/\/127\.0\.0\.1:8765\/playback\//);
 await expect.poll(()=>video.evaluate(v=>(v as HTMLVideoElement).readyState)).toBeGreaterThan(0);
 await page.goto('/login?next='+encodeURIComponent(new URL(url).pathname));
 await page.getByRole('button',{name:'Проверить как модератор'}).click();
 await page.getByRole('button',{name:'Одобрить',exact:true}).click();
 await expect(page.getByText('Ошибка обработки',{exact:true}).first()).toBeVisible({timeout:45000});
 await expect(page.getByRole('button',{name:'Повторить обработку'})).toBeVisible();
 await expect(page.locator('video')).toBeVisible();
 await expect(page.getByRole('button',{name:'Удалить только видео'})).toHaveCount(0);
});
