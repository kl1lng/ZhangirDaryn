const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const html = fs.readFileSync(path.join(__dirname, '..', 'web', 'avatar.html'), 'utf8');
const speechHtml = fs.readFileSync(path.join(__dirname, '..', 'web', 'index.html'), 'utf8');
const appPy = fs.readFileSync(path.join(__dirname, '..', 'app.py'), 'utf8');
const start = html.indexOf('function handTracked(');
const end = html.indexOf('function applyFacialMotion(', start);
assert.notEqual(start, -1, 'avatar hand tracking helpers exist');
assert.notEqual(end, -1, 'avatar hand tracking helpers have a closing boundary');
const trackingHelpers = html.slice(start, end);

function frameWithHands(leftX, rightX, faceMarker) {
  const frame = Array(162).fill(0);
  for (const [offset, x] of [[0, leftX], [63, rightX]]) {
    if (x == null) continue;
    frame[offset] = x;
    frame[offset + 1] = 0.5;
    frame[offset + 3] = x + 0.04;
    frame[offset + 4] = 0.5;
  }
  frame.fill(faceMarker, 126, 162);
  return frame;
}

function interpolate(sequence, maxGap = 3) {
  const context = { sequence, maxGap, result: null };
  vm.runInNewContext(
    `${trackingHelpers}\nresult = interpolateShortHandGaps(sequence, maxGap);`,
    context,
  );
  return Array.from(context.result, (frame) => Array.from(frame));
}

test('avatar interpolates short bilateral hand gaps without altering face data or source frames', () => {
  const source = [
    frameWithHands(0.4, 0.6, 0.1),
    frameWithHands(null, null, 0.2),
    frameWithHands(0.6, 0.4, 0.3),
  ];
  const result = interpolate(source, 1);

  assert.equal(result.length, 3);
  assert.equal(result[1][0], 0.5);
  assert.equal(result[1][3], 0.54);
  assert.equal(result[1][63], 0.5);
  assert.equal(result[1][66], 0.54);
  assert.deepEqual(result[1].slice(126), Array(36).fill(0.2));
  assert.equal(source[1][0], 0, 'interpolation does not mutate the database frame');
  assert.equal(source[1][126], 0.2);
});

test('avatar keeps long and boundary hand gaps instead of inventing movements', () => {
  const longGap = [
    frameWithHands(0.4, 0.6, 0.1),
    frameWithHands(null, null, 0.2),
    frameWithHands(null, null, 0.3),
    frameWithHands(null, null, 0.4),
    frameWithHands(0.6, 0.4, 0.5),
  ];
  const result = interpolate(longGap, 2);
  assert.equal(result[2][0], 0);
  assert.equal(result[2][63], 0);

  const boundaryGap = [frameWithHands(null, null, 0.1), frameWithHands(0.5, 0.5, 0.2)];
  assert.equal(interpolate(boundaryGap, 3)[0][0], 0);
});

test('avatar separates queued source clips with untracked frames, not interpolated signs', () => {
  const start = html.indexOf('function appendUntrackedFrames(');
  const end = html.indexOf('function applyFacialMotion(', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const sequence = [[.1, .2], [.3, .4]];
  const context = {sequence, result:null};
  vm.runInNewContext(
    `${html.slice(start, end)}\nresult=appendUntrackedFrames(sequence,2);`, context,
  );
  assert.deepEqual(Array.from(context.result, (frame) => Array.from(frame)), [
    [.1, .2], [.3, .4], [0, 0], [0, 0],
  ]);
  assert.deepEqual(sequence, [[.1, .2], [.3, .4]], 'source motion is not modified');
  assert.match(html, /if\(!interSignGap\)[\s\S]*?appendUntrackedFrames\(activeSequence,4\)/,
    'the playback queue inserts a short neutral gap between independent clips');
});

test('avatar preserves all measured 3-D hand orientation and uniform anatomy', () => {
  const poseStart = html.indexOf('function calculateHandPose(');
  const poseEnd = html.indexOf('function applyHand(', poseStart);
  assert.notEqual(poseStart, -1, 'pure hand pose transform exists');
  assert.notEqual(poseEnd, -1, 'pure hand pose transform has a boundary');
  const poseCode = html.slice(poseStart, poseEnd);
  const frame = Array(162).fill(0);
  const xy = [
    [0, 0], [-0.12, -0.04], [-0.16, -0.10], [-0.20, -0.15], [-0.23, -0.20],
    [-0.07, -0.20], [-0.08, -0.28], [-0.09, -0.34], [-0.10, -0.39],
    [0, -0.23], [0, -0.32], [0, -0.39], [0, -0.45],
    [0.07, -0.19], [0.08, -0.27], [0.09, -0.33], [0.10, -0.38],
    [0.13, -0.13], [0.15, -0.20], [0.17, -0.25], [0.19, -0.30],
  ];
  const wristX = 0.45, wristY = 0.70, wristZ = -0.12, angle = Math.PI / 4;
  xy.forEach(([x, y], i) => {
    frame[i * 3] = wristX + x;
    frame[i * 3 + 1] = wristY + y;
    frame[i * 3 + 2] = wristZ;
  });
  const rotated = frame.slice();
  for (let i = 0; i < 21; i++) {
    const x = frame[i * 3] - wristX, y = frame[i * 3 + 1] - wristY;
    rotated[i * 3 + 1] = wristY + y * Math.cos(angle);
    rotated[i * 3 + 2] = wristZ - y * Math.sin(angle);
  }
  const context = {
    frame, rotated, placement: {centerX: 0.5, centerY: 0.5, worldPerImageUnit: 2, imageAspectRatio: 1, targetY: 0.025},
    poses: null,
  };
  vm.runInNewContext(
    `${poseCode}\nposes = [calculateHandPose(frame, 0, placement), calculateHandPose(rotated, 0, placement)];`,
    context,
  );
  const [upright, tilted] = Array.from(context.poses);
  assert.ok(Math.abs(upright.points[1].x + 0.24) < 1e-10);
  assert.ok(Math.abs(upright.points[1].y - 0.08) < 1e-10);
  assert.ok(Math.abs(upright.points[1].z) < 1e-10);
  assert.ok(Math.abs(tilted.points[1].y - 0.08 * Math.cos(angle)) < 1e-10);
  assert.ok(Math.abs(tilted.points[1].z + 0.08 * Math.sin(angle)) < 1e-10,
    'out-of-plane palm rotation survives into the avatar geometry');
  assert.ok(Math.abs(upright.groupPosition[2] - (0.34 + 0.24)) < 1e-10,
    'wrist depth moves the complete hand in 3-D');
  assert.equal(upright.points.length, 21, 'all MediaPipe hand landmarks are retained');
  const handRenderer = html.slice(poseEnd, html.indexOf('let paused=', poseEnd));
  assert.match(handRenderer, /palmAcross\.clone\(\)\.cross\(palmLong\)/,
    'the palm surface orientation is derived from the measured hand plane');
  assert.match(handRenderer, /palmCore\.quaternion\.copy\(palmOrientation\)/,
    'palm volume rotates with the measured 3-D palm plane');
  assert.match(handRenderer, /mesh\.quaternion\.setFromRotationMatrix\(nailFrame\)/,
    'nail plates follow the individual finger direction and palm normal');
  assert.match(handRenderer, /raised\(p,\.019\)/,
    'finger webs are offset along the palm normal, not a fixed screen axis');
});

test('avatar anchors source body and hands to the tracked face instead of centering wrists', () => {
  const start = html.indexOf('function calibrateMotion(');
  const end = html.indexOf('function midpoint(', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const code = html.slice(start, end);
  const frame = Array(162).fill(0);
  // Nose at the face center; two anatomical wrists lower in the source frame.
  frame[126] = .5; frame[127] = .25;
  for (const offset of [0, 63]) {
    frame[offset] = offset ? .58 : .42;
    frame[offset + 1] = .72;
    frame[offset + 27] = frame[offset];
    frame[offset + 28] = .62;
  }
  const context = {
    sequence: [frame], activeImageAspectRatio: 16 / 9, result: null,
    THREE: {MathUtils: {clamp:(value,min,max)=>Math.max(min,Math.min(max,value))}},
  };
  vm.runInNewContext(`${code}\ncalibrateMotion(sequence); result=motionPlacement;`, context);
  assert.ok(Math.abs(context.result.centerY - .25) < 1e-12,
    'global vertical origin follows the measured nose, not low signing wrists');
  assert.ok(Math.abs(context.result.centerX - .5) < 1e-12);
  assert.equal(context.result.targetY, .58, 'source nose maps to avatar nose/face center');
  assert.match(html, /camera\.position\.set\(0,-\.18,3\.55\)/,
    'the complete upper-body gesture remains in frame');
});

test('pose arms attach to the nearest anatomical hands on mirrored footage', () => {
  const start = html.indexOf('function matchPoseWristHands(');
  const end = html.indexOf('function applyBodyPose(', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const matcher = html.slice(start, end);
  const context = { poseWrists: [{x:.44,y:.7},{x:.56,y:.7}], handWrists: [
    {x:.56,y:.7,visible:true},{x:.44,y:.7,visible:true},
  ], result: null };
  vm.runInNewContext(`${matcher}\nresult=matchPoseWristHands(poseWrists,handWrists);`, context);
  assert.deepEqual(Array.from(context.result), [1,0]);
  context.handWrists[1].visible = false;
  vm.runInNewContext(`${matcher}\nresult=matchPoseWristHands(poseWrists,handWrists);`, context);
  assert.deepEqual(Array.from(context.result), [1,0], 'one detected hand maps to its nearest pose wrist');
  assert.match(html, /const wristEnd=\(poseIndex,handIndex\)=>handWrists\[handIndex\]\.visible\s*\?handWrists\[handIndex\]\.group\.group\.position\.clone\(\):point\(4\+poseIndex\)/,
    'the forearm terminates at the exact 3-D wrist used by the hand rig');
});

test('speech player sends resume for a paused motion clip instead of reloading it', () => {
  const start = speechHtml.indexOf('function motionPlaybackMessage(');
  const end = speechHtml.indexOf("window.addEventListener('message'", start);
  assert.notEqual(start, -1, 'speech-to-motion control mapper exists');
  assert.notEqual(end, -1, 'speech-to-motion control mapper has a boundary');
  const code = speechHtml.slice(start, end);
  const context = {
    item: {type:'motion', label:'сәлем', sequence:[[1, 2, 3]], body_pose:[[.2,.3]], language:'kk-KZ', fps:24},
    result: null,
  };
  vm.runInNewContext(
    `${code}\nresult = [motionPlaybackMessage(item), motionPlaybackMessage(item, true)];`,
    context,
  );
  const [load, resume] = Array.from(context.result, (message) => ({...message}));
  assert.deepEqual(load, {type:'load-motion', sequence:[[1, 2, 3]], body_pose:[[.2,.3]], image_aspect_ratio:undefined, language:'kk-KZ', label:'сәлем', fps:24});
  assert.deepEqual(resume, {type:'resume'});
  assert.match(html, /message\.type==='resume'[\s\S]*?paused=false/);
  assert.match(speechHtml, /event\.source !== motionFrame\.contentWindow \|\| event\.origin !== 'http:\/\/localhost:8502'/);
  assert.match(html, /postMessage\(\{type:'motion-ended',label:activeLabel\},'\*'\)/);
  assert.match(speechHtml, /body_pose:segment\.body_pose \|\| metadata\.body_pose_landmarks \|\| null/,
    'text/speech translation must forward database pose landmarks to the avatar');
  assert.match(speechHtml, /language:segment\.language \|\| result\.language/,
    'the selected language must survive lookup and playback');
  assert.doesNotMatch(speechHtml, /const stopWords\s*=/,
    'untranslated grammatical words must not silently disappear');
  assert.match(appPy, /"body_pose": segment\.get\("metadata", \{\}\)\.get\("body_pose_landmarks"\)/,
    'the Streamlit avatar queue must carry pose landmarks from its motion segments');
  assert.ok(appPy.includes('"/*BODY_POSE__*/null"'),
    'the Streamlit avatar template must inject the first clip pose track');
  assert.ok(appPy.includes('"/*MOTION_LANGUAGE__*/\\"kk-KZ\\""'),
    'the Streamlit avatar template must receive the selected sign-language label');
});

test('speech player sends the remaining database clips to the avatar as one ordered queue', () => {
  const start = speechHtml.indexOf('function motionQueueMessage(');
  const end = speechHtml.indexOf("window.addEventListener('message'", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const context = {textLanguage:{value:'kk-KZ'}, result:null};
  vm.runInNewContext(
    `${speechHtml.slice(start, end)}\nresult=motionQueueMessage([`+
    `{type:'motion',label:'сәлем',sequence:[[1]],fps:24},`+
    `{type:'motion',label:'дос',sequence:[[2]],fps:30}],[]);`, context,
  );
  assert.equal(context.result.type, 'load-motion-queue');
  assert.deepEqual(Array.from(context.result.segments, item => item.label), ['сәлем','дос']);
  assert.deepEqual(Array.from(context.result.segments, item => item.language), ['kk-KZ','kk-KZ']);
  assert.match(speechHtml, /const payload = motionQueueMessage\(sequenceQueue\.slice\(currentIndex\), \[\]\)/,
    'the web player transfers the whole remaining phrase so each clip is not mistaken for the end');
  assert.match(speechHtml, /if \(motionQueueActive\) \{\s*motionQueueActive = false;\s*currentIndex = sequenceQueue\.length;\s*playNextItem\(\);/,
    'the one completion event ends the complete avatar queue instead of replaying its suffix');
  assert.match(html, /message\.type==='load-motion-queue'/);
});

test('one avatar completion event ends the full phrase queue without replaying its suffix', () => {
  const start = speechHtml.indexOf("window.addEventListener('message', event => {");
  const end = speechHtml.indexOf('\n\n        // Длительность показа одного жеста', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const observation = {completed:false};
  const state = {
    motionFrame:{contentWindow:{}}, isPlaying:true, motionMode:true,
    motionQueueActive:true, sequenceQueue:[{label:'сәлем'},{label:'дос'}],
    currentIndex:0, isPaused:true, observation,
  };
  const context = { ...state, window:{addEventListener(_name, callback){ this.messageListener=callback; }} };
  vm.runInNewContext(
    `${speechHtml.slice(start, end)}\nplayNextItem=()=>{observation.completed=currentIndex===sequenceQueue.length};\nwindow.messageListener({`+
    `source:motionFrame.contentWindow,origin:'http://localhost:8502',`+
    `data:{type:'motion-ended'}});`, context,
  );
  assert.equal(context.currentIndex, 2);
  assert.equal(context.motionQueueActive, false);
  assert.equal(context.isPaused, false);
  assert.equal(observation.completed, true, 'the parent transitions to completed state exactly at queue end');
});

test('speech fallback rejects placeholder media and reports untranslated letters', () => {
  const helperStart = speechHtml.indexOf('function legacyItemsForWord(');
  const helperEnd = speechHtml.indexOf('function showMissingMediaNotice(', helperStart);
  assert.notEqual(helperStart, -1);
  assert.notEqual(helperEnd, -1);
  const context = {result: null};
  vm.runInNewContext(
    `${speechHtml.slice(helperStart, helperEnd)}\nresult = legacyItemsForWord('әx', {ә:{driveId:'realDriveVideoId123456'}}, {ә:'DACTYL_ID_A', x:'DACTYL_ID_X'});`,
    context,
  );
  assert.equal(context.result.items.length, 0, 'placeholder-only fallback must not start broken videos');
  assert.deepEqual(Array.from(context.result.missing), ['ә', 'x']);
  assert.match(speechHtml, /const signDictionary = Object\.freeze\(\{\}\)/);
  assert.match(speechHtml, /const dactylDictionary = Object\.freeze\(\{\}\)/);
  assert.match(speechHtml, /https:\/\/www\.ai-ym\.kz\/ru\/dictionary/);

  vm.runInNewContext(
    `${speechHtml.slice(helperStart, helperEnd)}\nresult = legacyItemsForWord('ә', {ә:{driveId:'verifiedVideoId123456'}}, {});`,
    context,
  );
  assert.equal(context.result.items[0].driveId, 'verifiedVideoId123456');
  assert.deepEqual(Array.from(context.result.missing), []);
});

test('mixed database phrase preserves order and discloses missing lexical signs', () => {
  const start = speechHtml.indexOf('function legacyItemsForWord(');
  const end = speechHtml.indexOf('function showMissingMediaNotice(', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const context = {result: null};
  vm.runInNewContext(
    `${speechHtml.slice(start, end)}\nresult = queueFromMotionSegments({language:'kk-KZ', segments:[\n` +
    `{type:'motion', label:'сәлем', sequence:[[1]], metadata:{body_pose_landmarks:[[.1]], image_aspect_ratio:1.777}, fps:24},\n` +
    `{type:'missing', label:'әлем'},\n` +
    `{type:'motion', label:'дос', sequence:[[2]], fps:30}\n]}, {}, {ә:'verifiedLetterClip123456'});`,
    context,
  );
  assert.deepEqual(Array.from(context.result.queue, item => item.type), ['motion', 'dactyl', 'motion']);
  assert.deepEqual(Array.from(context.result.queue, item => item.label), ['сәлем', 'әлем (Ә)', 'дос']);
  assert.deepEqual(Array.from(context.result.unresolvedWords), ['әлем'],
    'letter-by-letter fallback must disclose that the full lexical sign was unavailable');
  assert.deepEqual(Array.from(context.result.queue[0].sequence[0]), [1]);
  assert.equal(context.result.queue[0].body_pose[0][0], .1);
  assert.equal(context.result.queue[0].image_aspect_ratio, 1.777);
  assert.equal(context.result.queue[0].fps, 24);
});

test('partial-translation warning stays visible while current playback status changes', () => {
  const start = speechHtml.indexOf('function showMissingMediaNotice(');
  const end = speechHtml.indexOf('// ============================================================\n        // 3.', start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const notice = {
    children: [],
    replaceChildren() { this.children = []; },
    append(item) { this.children.push(item); },
  };
  const status = {textContent:'', append() { throw new Error('warning must not share the volatile status node'); }};
  const context = {
    missingNotice: notice,
    statusText: status,
    document: {
      createTextNode(text) { return {text}; },
      createElement(tag) { return {tag}; },
    },
  };
  vm.runInNewContext(
    `${speechHtml.slice(start, end)}\nshowMissingMediaNotice(['әлем']);`, context,
  );
  status.textContent = 'Жест из motion-базы: сәлем';
  assert.equal(notice.children[0].text, 'Нет проверенных жестовых видео для: әлем. ');
  assert.equal(notice.children[1].tag, 'a');
  assert.equal(status.textContent, 'Жест из motion-базы: сәлем');
  vm.runInNewContext(
    `${speechHtml.slice(start, end)}\nshowMissingMediaNotice([]);`, context,
  );
  assert.deepEqual(notice.children, [], 'a fresh complete translation clears old warnings');
  assert.match(speechHtml, /missingNotice\.replaceChildren\(\);/,
    'starting a fresh playback clears stale warnings');
});
