import {test as base,expect} from '@playwright/test';

// The bundled shared collection would add hundreds of words to every stubbed library; specs start without it
// and register their own /rsl/catalog.json route (a later route wins) when they test it.
export const test=base.extend({page:async({page},use)=>{
 await page.route('**/rsl/catalog.json',route=>route.fulfill({json:[]}));
 await use(page);
}});
export {expect};
