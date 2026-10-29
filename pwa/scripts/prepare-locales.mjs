// Emit the same authored dictionary for the standalone offline shell.
import {readFile,writeFile} from 'node:fs/promises';
const dictionary=JSON.parse(await readFile(new URL('../lib/messages.json',import.meta.url),'utf8'));
await writeFile(new URL('../public/offline-locales.js',import.meta.url),'window.DOSYM_MESSAGES='+JSON.stringify(dictionary)+';\n');
