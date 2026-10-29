import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const baseURL = process.env.DOSYM_PROFILE_URL || 'http://127.0.0.1:3000';
const phrase = process.env.DOSYM_PROFILE_PHRASE || 'salem';
const browser = await chromium.launch({ channel: 'msedge', headless: true });
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  const motionResponses = [];
  const failedRequests = [];
  page.on('requestfailed', request => failedRequests.push({
    path: new URL(request.url()).pathname,
    error: request.failure()?.errorText,
  }));
  page.on('response', response => {
    if (response.url().includes('/motion')) motionResponses.push({ status: response.status(), url: new URL(response.url()).pathname });
  });
  await page.addInitScript(() => {
    localStorage.setItem('dosym-locale', 'ru');
    const metrics = { raf: 0, longTasks: [], preparationChunks: [], lcp: null };
    Object.defineProperty(window, '__dosymPerformance', { value: metrics });
    const nativeRaf = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = callback => nativeRaf(time => { metrics.raf++; callback(time); });
    try {
      new PerformanceObserver(list => metrics.longTasks.push(...list.getEntries().map(entry => ({
        durationMs: entry.duration,
        attribution: entry.attribution?.map(item => ({containerType:item.containerType,containerName:item.containerName,containerId:item.containerId})) ?? [],
      }))))
        .observe({ type: 'longtask', buffered: true });
      new PerformanceObserver(list => { metrics.lcp = list.getEntries().at(-1)?.startTime ?? metrics.lcp; })
        .observe({ type: 'largest-contentful-paint', buffered: true });
    } catch {}
  });
  const navStarted = Date.now();
  await page.goto(baseURL, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'сәлем', exact: true }).waitFor({ timeout: 15000 });
  const firstScreen = await page.evaluate(() => ({
    avatarFrames: document.querySelectorAll('.player iframe').length,
    resourceTransferBytes: performance.getEntriesByType('resource').reduce((sum, entry) => sum + (entry.transferSize || 0), 0),
    largestResources: performance.getEntriesByType('resource').map(entry => ({
      path: new URL(entry.name).pathname,
      transferBytes: entry.transferSize || 0,
    })).sort((a, b) => b.transferBytes - a.transferBytes).slice(0, 10),
  }));
  if (firstScreen.avatarFrames !== 0) throw new Error('Avatar iframe loaded before a gesture was selected.');

  await page.getByLabel('Текст для показа жестами').fill(phrase);
  const motionResponsePromise = page.waitForResponse(response => response.url().includes('/motion') && response.ok(), { timeout: 15000 })
    .then(response => response.json()).catch(() => null);
  const playbackStarted = Date.now();
  await page.getByRole('button', { name: 'Показать жесты', exact: true }).click();
  await page.locator('.player iframe').waitFor({ timeout: 15000 });
  const frame = page.frames().find(candidate => candidate.url().endsWith('/avatar/index.html'));
  if (!frame) throw new Error('Avatar frame missing. Frames=' + JSON.stringify(page.frames().map(item=>item.url())) + ' body=' + (await page.locator('body').innerText()).slice(0,800));
  const playButton = page.locator('.player-controls .round-button');
  try {
    await page.waitForFunction(() => document.querySelector('.player-controls .round-button')?.getAttribute('aria-label') === 'Приостановить', undefined, { timeout: 15000 });
  } catch {
    const pageText = (await page.locator('body').innerText()).slice(0, 1000);
    throw new Error(`Gesture playback did not start. Motion responses: ${JSON.stringify(motionResponses)}. Failed requests: ${JSON.stringify(failedRequests)}. Page: ${pageText}`);
  }
  const motion = await motionResponsePromise;
  if (!motion) throw new Error(`Could not read the motion response: ${JSON.stringify(motionResponses)}`);
  await page.waitForFunction(() => {
    const caption=document.querySelector('.player iframe')?.contentDocument?.querySelector('#caption')?.textContent||'';
    return caption.includes('Воспроизведение из motion-базы')||caption.includes('Клип завершён');
  }, undefined, { timeout: 20000 });
  const firstPlayMs = Date.now() - playbackStarted;
  await page.waitForTimeout(400);
  await playButton.click();
  await page.waitForFunction(() => document.querySelector('.player-controls .round-button')?.getAttribute('aria-label') === 'Продолжить');
  await page.waitForFunction(() => document.querySelector('.player iframe')?.contentDocument?.querySelector('#caption')?.textContent === 'Воспроизведение приостановлено.');
  const pauseStart = await frame.evaluate(() => (window).__dosymPerformance?.raf ?? -1);
  await page.waitForTimeout(500);
  const pauseEnd = await frame.evaluate(() => (window).__dosymPerformance?.raf ?? -1);
  await playButton.click();
  await page.waitForFunction(() => document.querySelector('.player-controls .round-button')?.getAttribute('aria-label') === 'Приостановить');
  await page.waitForFunction(() => document.querySelector('.player iframe')?.contentDocument?.querySelector('#caption')?.textContent?.startsWith('Воспроизведение продолжается'));
  await page.locator('.player-controls .round-button[aria-label="Воспроизвести"]').waitFor({ timeout: 15000 });
  await page.waitForTimeout(600);
  const idleStart = await frame.evaluate(() => (window).__dosymPerformance?.raf ?? -1);
  await page.waitForTimeout(600);
  const idleEnd = await frame.evaluate(() => (window).__dosymPerformance?.raf ?? -1);

  const browserMetrics = await page.evaluate(() => ({
    userAgent: navigator.userAgent,
    viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
    elapsedPageMs: performance.now(),
    lcpMs: (window).__dosymPerformance?.lcp,
    longTasksMs: (window).__dosymPerformance?.longTasks ?? [],
    resourceTransferBytes: performance.getEntriesByType('resource').reduce((sum, entry) => sum + (entry.transferSize || 0), 0),
  }));
  browserMetrics.firstScreenResourceTransferBytes = firstScreen.resourceTransferBytes;
  browserMetrics.firstScreenAvatarFrames = firstScreen.avatarFrames;
  browserMetrics.firstScreenLargestResources = firstScreen.largestResources;
  const frameMetrics = await frame.evaluate(() => ({
    idleRafDelta: -1,
    longTasksMs: (window).__dosymPerformance?.longTasks ?? [],
    preparationChunks: (window).__dosymPerformance?.preparationChunks ?? [],
  }));
  frameMetrics.idleRafDelta = idleEnd - idleStart;
  const report = {
    measuredAt: new Date().toISOString(), baseURL, phrase, browser: browserMetrics,
    frame: frameMetrics,
    failedRequests,
    playback: {
      firstPlayMs,
      pauseRafDeltaDuring500ms: pauseEnd - pauseStart,
      clipFrames: Array.isArray(motion.sequence) ? motion.sequence.length : null,
      sourceFps: motion.fps,
      clipDurationMs: Array.isArray(motion.sequence) && Number(motion.fps) > 0 ? motion.sequence.length / Number(motion.fps) * 1000 : null,
    },
    navigationWallMs: Date.now() - navStarted,
  };
  const output = path.join(root, 'data', 'pwa', 'performance');
  await mkdir(output, { recursive: true });
  const reportPath = path.join(output, `profile-${Date.now()}.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ reportPath, ...report }, null, 2));
} finally {
  await browser.close();
}
