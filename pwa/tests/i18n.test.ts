import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DEFAULT_LOCALE,isLocale,translate,translatedError} from '../lib/i18n.ts';
import {messages} from '../lib/messages.ts';
import ts from 'typescript';
import {readFileSync} from 'node:fs';
test('Kazakh is the default and only supported persisted locales are accepted',()=>{
 assert.equal(DEFAULT_LOCALE,'kk');
 assert.ok(isLocale('kk'));assert.ok(isLocale('en'));assert.equal(isLocale('de'),false);
 assert.equal(translate('Слова становятся движением'),'Сөздер қимылға айналады');
 assert.equal(translate('Слова становятся движением','en'),'Words become movement');
 assert.equal(translate('Сәлем','en'),'Сәлем');
 assert.equal(translate('Передано {0}%','kk',{'0':35}),'35% жіберілді');
});
test('every authored message has both translations and preserves placeholders',()=>{
 for(const [source,pair] of Object.entries(messages)){
  for(const translation of pair){assert.ok(translation.trim(),source);assert.deepEqual(translation.match(/\{\d+\}/g)||[],source.match(/\{\d+\}/g)||[],source);}
 }
 assert.equal(translatedError('unexpected server detail','en'),'Could not complete the action.');
});
test('every static React translation call has an authored dictionary entry',()=>{
 for(const name of ['workspace','uploads','materials','player','offline','locale']){
  const path=new URL('../features/'+name+'.tsx',import.meta.url);
  const source=ts.createSourceFile(path.pathname,readFileSync(path,'utf8'),ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  function visit(node:ts.Node){
   if(ts.isCallExpression(node)&&node.expression.getText(source)==='t'&&node.arguments[0]&&ts.isStringLiteral(node.arguments[0])){
    const key=node.arguments[0].text.replace(/\s+/g,' ').trim();assert.ok(messages[key],name+': '+key);
   }
   ts.forEachChild(node,visit);
  }
  visit(source);
 }
});
