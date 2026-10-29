import { test, expect } from '@playwright/test';

test.beforeEach(async({page})=>{await page.addInitScript(()=>localStorage.setItem('dosym-locale','ru'));});

test('guest sees the actual workspace and must sign in to upload', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Слова становятся движением' })).toBeVisible();
  await page.getByRole('link', { name: 'Добавить видео', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Ваш вклад начинается со входа' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Продолжить с Google' })).toBeVisible();
});

test('local user sees their uploads but cannot moderate', async ({ page }) => {
  await page.goto('/login?next=/upload');
  await page.getByRole('button', { name: 'Проверить как участник' }).click();
  await expect(page.getByRole('heading', { name: 'Поделитесь одним жестом' })).toBeVisible();
  await page.goto('/moderation');
  await expect(page.getByText('Этот раздел доступен модератору.')).toBeVisible();
});

test('moderator sees empty queue and training prerequisites', async ({ page }) => {
  await page.goto('/login?next=/moderation');
  await page.getByRole('button', { name: 'Проверить как модератор' }).click();
  await expect(page.getByRole('heading', { name: 'Проверка материалов' })).toBeVisible();
  await page.goto('/model');
  await expect(page.getByText('Нужны минимум два класса и два независимых исполнителя в каждом классе.')).toBeVisible();
});

test('mobile layout fits and keeps navigation accessible', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
  await page.getByRole('link', { name: 'Словарь', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Библиотека жестов' })).toBeVisible();
});

test('empty dictionary does not claim unavailable translations', async ({ page }) => {
  await page.goto('/dictionary');
  await expect(page.getByText('Библиотека пока пуста')).toBeVisible();
  await page.goto('/');
  await page.getByLabel('Текст для показа жестами').fill('Несуществующее слово');
  await page.getByRole('button', { name: 'Показать жесты' }).click();
  await expect(page.getByText(/Пока нет жестов для/)).toBeVisible();
});

test('proxy rejects a foreign origin when minting local identities',async({request})=>{
 const response=await request.post('/api/auth/local',{headers:{Origin:'https://attacker.example'},data:{role:'moderator'}});
 expect(response.status()).toBe(403);
});

test('proxy never accepts local credentials even with a forged loopback Host',async({request})=>{
 const response=await request.get('/api/me',{headers:{Host:'localhost:3000',Authorization:'Bearer local:forged'}});
 expect(response.status()).toBe(403);
});
