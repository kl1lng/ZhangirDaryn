import {test,expect} from '@playwright/test';
import {readFile} from 'node:fs/promises';

async function fakeCamera(page:any,{delayed=false,denied=false}={}){
 await page.addInitScript(({delayed,denied}:{delayed:boolean;denied:boolean})=>{
  localStorage.setItem('dosym-locale','ru');
  (window as any).cameraCalls=0;
  const stream={getTracks:()=>[{stop(){(window as any).tracksStopped=((window as any).tracksStopped||0)+1;}}]};
  Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:()=>{(window as any).cameraCalls++;if(denied)return Promise.reject(new DOMException('Denied','NotAllowedError'));if(delayed)return new Promise(resolve=>(window as any).grantCamera=()=>resolve(stream));return Promise.resolve(stream);}}});
  Object.defineProperty(HTMLMediaElement.prototype,'srcObject',{configurable:true,set(){},get(){return null;}});
  Object.defineProperty(HTMLMediaElement.prototype,'readyState',{configurable:true,get(){return 4;}});
  Object.defineProperty(HTMLVideoElement.prototype,'videoWidth',{configurable:true,get(){return 640;}});
  Object.defineProperty(HTMLVideoElement.prototype,'videoHeight',{configurable:true,get(){return 480;}});
  HTMLMediaElement.prototype.play=()=>Promise.resolve();
  (window as any).createImageBitmap=async()=>({close(){}});
  (window as any).Worker=class {
   onmessage:any;onerror:any;
   constructor(){(window as any).cameraWorker=this;}
   postMessage(message:any){queueMicrotask(()=>this.onmessage?.({data:message.type==='init'?{type:'ready',count:2}:{type:'result',hands:1,landmarks:[],collecting:false,candidates:[{id:'example-a',label:'А',distance:.1}]}}));}
   terminate(){(window as any).workerStopped=true;}
  };
 },{delayed,denied});
}

test('camera only starts on request, shows candidates and releases hardware on navigation',async({page})=>{
 await fakeCamera(page);await page.goto('/camera');
 expect(await page.evaluate(()=>(window as any).cameraCalls)).toBe(0);
 await page.getByRole('button',{name:'Включить камеру',exact:true}).click();
 await expect(page.getByRole('link',{name:'А',exact:true})).toBeVisible();
 await page.getByRole('link',{name:'Словарь',exact:true}).first().click();
 await expect(page).toHaveURL(/\/dictionary$/);
 await expect.poll(()=>page.evaluate(()=>(window as any).tracksStopped)).toBe(1);
 expect(await page.evaluate(()=>(window as any).workerStopped)).toBe(true);
});

test('cancelling before permission resolves stops a late camera stream',async({page})=>{
 await fakeCamera(page,{delayed:true});await page.goto('/camera');
 await page.getByRole('button',{name:'Включить камеру',exact:true}).click();
 await expect.poll(()=>page.evaluate(()=>(window as any).cameraCalls)).toBe(1);
 await page.getByRole('button',{name:'Остановить камеру',exact:true}).click();
 await page.evaluate(()=>(window as any).grantCamera());
 await expect.poll(()=>page.evaluate(()=>(window as any).tracksStopped)).toBe(1);
 await expect(page.getByRole('button',{name:'Включить камеру',exact:true})).toBeEnabled();
});

test('permission denial is actionable and leaves no active worker',async({page})=>{
 await fakeCamera(page,{denied:true});await page.goto('/camera');
 await page.getByRole('button',{name:'Включить камеру',exact:true}).click();
 await expect(page.getByText('Разрешите доступ к камере в настройках браузера.')).toBeVisible();
 expect(await page.evaluate(()=>(window as any).workerStopped)).toBe(true);
});

test('missing hands clear results and hiding the tab releases the camera',async({page})=>{
 await fakeCamera(page);await page.goto('/camera');
 await page.getByRole('button',{name:'Включить камеру',exact:true}).click();
 await expect(page.getByRole('link',{name:'А',exact:true})).toBeVisible();
 await page.evaluate(()=>{const engine=(window as any).cameraWorker;engine.postMessage=()=>{};engine.onmessage({data:{type:'result',hands:0,landmarks:[],collecting:true,candidates:[]}});});
 await expect(page.getByRole('link',{name:'А',exact:true})).toHaveCount(0);
 await expect(page.getByText('Руки не видны в кадре.')).toBeVisible();
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,get:()=>true});document.dispatchEvent(new Event('visibilitychange'));});
 await expect.poll(()=>page.evaluate(()=>(window as any).tracksStopped)).toBe(1);
 await expect(page.getByRole('button',{name:'Включить камеру',exact:true})).toBeEnabled();
});

test('mobile camera view fits, translates, and does not load vision assets before start',async({page})=>{
 await page.setViewportSize({width:360,height:800});
 const downloads:string[]=[];page.on('request',request=>{if(request.url().includes('/camera/'))downloads.push(request.url());});
 await page.goto('/camera');
 await expect(page.getByRole('heading',{name:'Камера: ымнан мәтінге'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.getByRole('combobox',{name:'Интерфейс тілі'}).selectOption('en');
 await expect(page.getByRole('heading',{name:'Camera: signs to text'})).toBeVisible();
 await expect(page.getByRole('button',{name:'Start camera',exact:true})).toBeVisible();
 expect(downloads).toEqual([]);
});

test('real MediaPipe worker loads local assets and detects no hands in a blank frame',async({page})=>{
 test.setTimeout(120000);
 await page.route('**/camera-test-references',route=>route.fulfill({json:{schema:1,references:[{id:'a',label:'А',sequence:Array.from({length:16},()=>Array.from({length:126},(_,i)=>i<63?.2+i*.001:0))},{id:'b',label:'Б',sequence:Array.from({length:16},()=>Array.from({length:126},(_,i)=>i>=63?.2+i*.001:0))}]}}));
 await page.goto('/camera');
 const result=await page.evaluate(()=>new Promise<any>((resolve,reject)=>{
  const worker=new Worker('/camera/worker.js');const timer=setTimeout(()=>{worker.terminate();reject(new Error('Worker initialization timed out'));},60000);
  worker.onerror=event=>{clearTimeout(timer);worker.terminate();reject(new Error(event.message));};
  worker.onmessage=async({data})=>{if(data.type==='error'){clearTimeout(timer);worker.terminate();reject(new Error(data.code));}if(data.type==='ready'){const canvas=new OffscreenCanvas(320,240);canvas.getContext('2d')!.fillRect(0,0,320,240);const bitmap=await createImageBitmap(canvas);worker.postMessage({type:'frame',bitmap,timestamp:performance.now()},[bitmap]);}if(data.type==='result'){clearTimeout(timer);worker.terminate();resolve(data);}};
  worker.postMessage({type:'init',referenceUrl:location.origin+'/camera-test-references'});
 }));
 expect(result.hands).toBe(0);expect(result.candidates).toEqual([]);
});

test('real worker matches an explicitly supplied local recording without uploading video',async({page})=>{
 test.skip(!process.env.DOSYM_CAMERA_TEST_VIDEO,'Set an authorized local recording for this optional integration check.');
 test.setTimeout(120000);
 const bytes=await readFile(process.env.DOSYM_CAMERA_TEST_VIDEO!);
 await page.route('**/recorded-sign.mp4',route=>route.fulfill({body:bytes,contentType:'video/mp4'}));
 await page.goto('/camera');
 const result=await page.evaluate((referenceUrl)=>new Promise<{hands:number;labels:string[]}>((resolve,reject)=>{
  const worker=new Worker('/camera/worker.js'),video=document.createElement('video');video.muted=true;video.playsInline=true;video.style.cssText='position:fixed;right:0;bottom:0;width:320px;z-index:9999';document.body.append(video);
  const timer=setTimeout(()=>{worker.terminate();reject(new Error('Recording check timed out'));},90000);
  const finish=(error?:Error)=>{clearTimeout(timer);worker.terminate();video.removeAttribute('src');video.load();video.remove();if(error)reject(error);};
  worker.onerror=event=>finish(new Error(event.message));
  let index=0,hands=0;const labels=new Set<string>();
  const capture=()=>{video.requestVideoFrameCallback(async()=>{try{
   const width=Math.min(640,video.videoWidth),height=Math.round(width*video.videoHeight/video.videoWidth);
   const bitmap=await createImageBitmap(video,{resizeWidth:width,resizeHeight:height});
   worker.postMessage({type:'frame',bitmap,timestamp:performance.now()},[bitmap]);
  }catch(error){finish(error as Error);}});};
  worker.onmessage=async({data})=>{
   if(data.type==='error'){finish(new Error(data.code));return;}
   if(data.type==='ready'){await new Promise<void>((done,fail)=>{video.onloadedmetadata=()=>done();video.onerror=()=>fail(new Error('Cannot load recording'));video.src=location.origin+'/recorded-sign.mp4';});video.loop=true;await video.play();capture();}
   if(data.type==='result'){hands+=data.hands;data.candidates.forEach((row:{label:string})=>labels.add(row.label));index++;if(index<50)setTimeout(capture,100);else{finish();resolve({hands,labels:[...labels]});}}
  };
  worker.postMessage({type:'init',referenceUrl});
 }),process.env.DOSYM_CAMERA_TEST_LIBRARY!);
 expect(result.hands).toBeGreaterThan(0);
 expect(result.labels).toContain(process.env.DOSYM_CAMERA_TEST_LABEL);
});
