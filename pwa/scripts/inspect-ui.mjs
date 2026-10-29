import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
await mkdir('test-results/visual',{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
const failures=[];page.on('pageerror',e=>failures.push(e.message));
await page.goto('http://127.0.0.1:3000/');
await page.getByRole('heading',{name:'Слова становятся движением'}).waitFor();
await page.waitForTimeout(2500);
await page.screenshot({path:'test-results/visual/desktop.png',fullPage:true});
const frame=page.frames().find(f=>f.url().includes('/avatar/index.html'));
console.log(JSON.stringify({failures,avatar:frame?await frame.evaluate(()=>({canvas:!!document.querySelector('canvas'),width:document.querySelector('canvas')?.width,height:document.querySelector('canvas')?.height,caption:document.querySelector('#caption')?.textContent})):null}));
await page.setViewportSize({width:390,height:844});
await page.screenshot({path:'test-results/visual/mobile.png',fullPage:true});
for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});console.log(JSON.stringify({width,overflow:await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)}));}
await browser.close();
