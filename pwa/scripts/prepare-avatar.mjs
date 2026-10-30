// Build public playback from the single maintained avatar source, not a fork.
import { readFile, writeFile, mkdir, copyFile } from 'node:fs/promises';
import path from 'node:path';
import './prepare-locales.mjs';
import './prepare-camera.mjs';
const root=path.resolve(import.meta.dirname,'../..');
const output=path.join(root,'pwa/public/avatar');
await mkdir(path.join(output,'models'),{recursive:true});
await mkdir(path.join(output,'vendor/loaders'),{recursive:true});
await mkdir(path.join(output,'vendor/utils'),{recursive:true});
const replacements={
  'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js':'/avatar/vendor/three.module.js',
  'https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/loaders/GLTFLoader.js':'/avatar/vendor/loaders/GLTFLoader.js',
  'http://127.0.0.1:8502/rig-motion.mjs':'/avatar/rig-motion.mjs',
  'http://127.0.0.1:8502/render-scheduler.mjs':'/avatar/render-scheduler.mjs',
  'http://127.0.0.1:8502/models/rocketbox-male-adult-02.glb':'/avatar/models/rocketbox-male-adult-02.glb',
  '__MOTION_SEQUENCE__':'[]','__MOTION_LABEL__':'""','__MOTION_FPS__':'30',
};
let html=await readFile(path.join(root,'web/avatar.html'),'utf8');
for(const [from,to] of Object.entries(replacements)) html=html.replaceAll(from,to);
html=html.replace('</head>',`<style>
body{background:#eaf0f7;padding:0;color:#263e57}main{max-width:none;padding:0;border:0;box-shadow:none;border-radius:0;background:transparent}
header,.controls,.timeline,.caption,.preparation,#empty{display:none!important}body{display:block}main.stage{width:100%;height:100vh;padding:0;background:transparent;border:0;border-radius:0;box-shadow:none;backdrop-filter:none}#scene{height:100vh;min-height:260px;border:0;border-radius:0;background:#eaf0f7}
</style></head>`);
html=html.replace("if(event.source!==window.parent||!event.data", "if(event.origin!==location.origin||event.source!==window.parent||!event.data");
html=html.replace("window.parent.postMessage({type:'motion-ended',label:activeLabel},'*')","window.parent.postMessage({type:'motion-ended',label:activeLabel},location.origin)");
// Reveal the canvas only after a prepared motion frame, never the loading rig.
html=html.replace('</head>','<style>#canvas{visibility:hidden}</style></head>');
html=html.replace('  preparing=true;',"  preparing=true;parent.postMessage({type:'avatar-preparing'},location.origin);");
html=html.replace('  renderFrame();playTimer=',"  renderFrame();document.querySelector('#canvas').style.visibility='visible';parent.postMessage({type:'avatar-frame-ready'},location.origin);playTimer=");
html=html.replace('</body>',`<script>window.addEventListener('load',()=>parent.postMessage({type:'avatar-ready'},location.origin));</script></body>`);
html=html.replace("  if(activeBodyPose){\n    handL.group.visible=false;handR.group.visible=false;", "  if(true){\n    handL.group.visible=false;handR.group.visible=false;");
html=html.replace('<script type="module">','<script>window.addEventListener("error",()=>parent.postMessage({type:"avatar-error"},location.origin));</script><script type="module">');
html=html.replace('function frameCamera(){camera.position.set(0,.32,2.05);camera.lookAt(0,.32,0);camera.updateProjectionMatrix()}',
 'function frameCamera(){camera.position.set(0,.08,Math.max(2.7,2.2/Math.max(.7,camera.aspect)));camera.lookAt(0,.08,0);camera.updateProjectionMatrix()}');
await writeFile(path.join(output,'index.html'),html);
await copyFile(path.join(root,'web/rig-motion.mjs'),path.join(output,'rig-motion.mjs'));
await copyFile(path.join(root,'web/render-scheduler.mjs'),path.join(output,'render-scheduler.mjs'));
for(const file of ['rocketbox-male-adult-02.glb','ROCKETBOX_LICENSE.md'])
  await copyFile(path.join(root,'web/models',file),path.join(output,'models',file));
const three=path.join(root,'pwa/node_modules/three');
await copyFile(path.join(three,'build/three.module.js'),path.join(output,'vendor/three.module.js'));
await copyFile(path.join(three,'examples/jsm/loaders/GLTFLoader.js'),path.join(output,'vendor/loaders/GLTFLoader.js'));
await copyFile(path.join(three,'examples/jsm/utils/BufferGeometryUtils.js'),path.join(output,'vendor/utils/BufferGeometryUtils.js'));
await copyFile(path.join(three,'LICENSE'),path.join(output,'vendor/LICENSE'));
await writeFile(path.join(output,'assets.json'),JSON.stringify([
 '/avatar/index.html','/avatar/rig-motion.mjs','/avatar/render-scheduler.mjs','/avatar/models/rocketbox-male-adult-02.glb',
 '/avatar/vendor/three.module.js','/avatar/vendor/loaders/GLTFLoader.js','/avatar/vendor/utils/BufferGeometryUtils.js',
]));
console.log('Prepared avatar and local dependencies from maintained source.');
