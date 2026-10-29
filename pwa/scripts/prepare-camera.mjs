// Generated, same-origin runtime. No remote JS is loaded when the camera runs.
import {mkdir,readFile,writeFile,copyFile,readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import ts from 'typescript';
const root=path.resolve(import.meta.dirname,'../..'),output=path.join(root,'pwa/public/camera');
const dependency=path.join(root,'pwa/node_modules/@mediapipe/tasks-vision');
await mkdir(path.join(output,'wasm'),{recursive:true});
for(const file of await readdir(path.join(dependency,'wasm')))await copyFile(path.join(dependency,'wasm',file),path.join(output,'wasm',file));
const model=await readFile(path.join(root,'hand_landmarker.task'));
const checksum=createHash('sha256').update(model).digest('hex');
if(checksum!=='fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1')throw new Error('Unexpected hand model checksum. Review model before release.');
await writeFile(path.join(output,'hand_landmarker.task'),model);
// The package CJS bundle has no require calls. A classic worker provides exports
// and supports importScripts required by the MediaPipe WASM loader.
await writeFile(path.join(output,'vision.js'),'var exports={};\n'+await readFile(path.join(dependency,'vision_bundle.cjs'),'utf8'));
const matcher=await readFile(path.join(root,'pwa/lib/camera-match.ts'),'utf8');
await writeFile(path.join(output,'matcher.js'),ts.transpileModule(matcher,{compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS}}).outputText);
await copyFile(path.join(root,'web/camera-worker.js'),path.join(output,'worker.js'));
await writeFile(path.join(output,'NOTICE.txt'),'MediaPipe Tasks Vision 0.10.32 and Hand Landmarker: Google / Apache-2.0.\nhttps://github.com/google-ai-edge/mediapipe\nModel SHA-256: '+checksum+'\n');
console.log('Prepared local camera runtime and verified hand model.');
