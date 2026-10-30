import {test,expect} from '@playwright/test';

test('speech appends final text once, keeps interim text separate and stops on navigation',async({page})=>{
 await page.addInitScript(()=>{
  localStorage.setItem('dosym-locale','ru');
  class FakeRecognition{
   lang='';interimResults=false;continuous=false;onstart:Function|null=null;onresult:Function|null=null;onerror:Function|null=null;onend:Function|null=null;
   start(){(window as any).speechInstance=this;this.onstart?.();}
   stop(){this.onend?.();}
   abort(){(window as any).speechAborted=true;this.onend?.();}
  }
  (window as any).SpeechRecognition=FakeRecognition;
 });
 await page.goto('/');
 await page.getByLabel('Текст для показа жестами').fill('А');
 await page.getByRole('button',{name:'Начать голосовой ввод'}).click();
 expect(await page.evaluate(()=>(window as any).speechInstance.lang)).toBe('ru-RU');
 await page.evaluate(()=>(window as any).speechInstance.onresult({resultIndex:0,results:[Object.assign([{transcript:'Сәлем'}],{isFinal:false})]}));
 await expect(page.getByLabel('Текст для показа жестами')).toHaveValue('А');
 await expect(page.getByText('Сәлем',{exact:true})).toBeVisible();
 await page.evaluate(()=>(window as any).speechInstance.onresult({resultIndex:0,results:[Object.assign([{transcript:'Сәлем'}],{isFinal:true})]}));
 await expect(page.getByLabel('Текст для показа жестами')).toHaveValue('А Сәлем');
 await page.evaluate(()=>(window as any).speechInstance.onresult({resultIndex:0,results:[Object.assign([{transcript:'Сәлем'}],{isFinal:true})]}));
 await expect(page.getByLabel('Текст для показа жестами')).toHaveValue('А Сәлем');
 await page.getByRole('link',{name:'Словарь',exact:true}).first().click();
 await expect(page).toHaveURL(/\/dictionary$/);
 await expect.poll(()=>page.evaluate(()=>(window as any).speechAborted)).toBe(true);
});

test('unsupported speech remains explicit and does not disable text entry',async({page})=>{
 await page.addInitScript(()=>{localStorage.setItem('dosym-locale','ru');(window as any).SpeechRecognition=undefined;(window as any).webkitSpeechRecognition=undefined;});
 await page.goto('/');
 await expect(page.getByText('Голосовой ввод недоступен в этом браузере.')).toBeVisible();
 await expect(page.getByLabel('Текст для показа жестами')).toBeEditable();
});

