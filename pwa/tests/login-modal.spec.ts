import {test,expect} from './fixtures';

test.use({serviceWorkers:'block'});
test.beforeEach(async({page})=>{
 await page.route('**/api/auth/config',route=>route.fulfill({json:{auth_provider:'google',google_configured:true,local_auth:false,storage:'local'}}));
 await page.route('**/api/me',route=>route.fulfill({status:401,json:{error:'Sign in'}}));
 await page.route('**/api/gestures',route=>route.fulfill({json:[]}));
});

for(const path of ['/upload','/my']){
 test(`guest opening ${path} gets a sign-in dialog that Escape closes`,async({page})=>{
  await page.goto(path);
  const dialog=page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole('button',{name:/Google/})).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole('dialog')).toHaveCount(0);
 });
}

test('clicking the dimmed backdrop closes the dialog',async({page})=>{
 await page.goto('/upload');
 await expect(page.getByRole('dialog')).toBeVisible();
 await page.mouse.click(4,4);
 await expect(page).toHaveURL(/\/$/);
});
