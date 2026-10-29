const assert = require('node:assert/strict');
const test = require('node:test');

function createFrameQueue() {
  let nextId = 0;
  const callbacks = new Map();
  return {
    requestFrame(callback) { const id = ++nextId; callbacks.set(id, callback); return id; },
    cancelFrame(id) { callbacks.delete(id); },
    flush() { const pending = [...callbacks.values()]; callbacks.clear(); pending.forEach(callback => callback()); },
    get size() { return callbacks.size; },
  };
}

test('render invalidations coalesce into one frame', async () => {
  const { createRenderScheduler } = await import('../web/render-scheduler.mjs');
  const queue = createFrameQueue();
  let renders = 0;
  const scheduler = createRenderScheduler({ ...queue, render: () => renders++ });

  scheduler.invalidate();
  scheduler.invalidate();
  assert.equal(queue.size, 1);
  queue.flush();
  assert.equal(renders, 1);
});

test('hidden or disposed scenes cancel pending draws and never render', async () => {
  const { createRenderScheduler } = await import('../web/render-scheduler.mjs');
  const queue = createFrameQueue();
  let renders = 0;
  const scheduler = createRenderScheduler({ ...queue, render: () => renders++ });

  scheduler.invalidate();
  scheduler.setVisible(false);
  assert.equal(queue.size, 0);
  queue.flush();
  assert.equal(renders, 0);

  scheduler.setVisible(true);
  assert.equal(queue.size, 1);
  scheduler.dispose();
  queue.flush();
  assert.equal(renders, 0);
  assert.equal(queue.size, 0);
});
