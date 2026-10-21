import assert from 'node:assert/strict';
import { mock, test } from 'node:test';

import { followAppHeight, SETTLE_MS } from '../src/lib/appHeight.ts';

/** A number signal the way the SDK's viewport hands one out: silent when nothing changed. */
function signal(initial: number) {
  let value = initial;
  const subscribers = new Set<(value: number) => void>();
  const read = () => value;
  return Object.assign(read, {
    sub(fn: (value: number) => void) {
      subscribers.add(fn);
      return () => subscribers.delete(fn);
    },
    set(next: number) {
      if (next === value) return;
      value = next;
      for (const fn of subscribers) fn(next);
    },
  });
}

function setup(height = 0, stableHeight = 0) {
  mock.timers.enable({ apis: ['setTimeout'] });
  const viewport = { height: signal(height), stableHeight: signal(stableHeight) };
  const published: number[] = [];
  const stop = followAppHeight(viewport, (px) => published.push(px));
  return { viewport, published, stop };
}

test('a stable height is published as soon as Telegram reports it', (t) => {
  t.after(() => mock.timers.reset());
  const { viewport, published } = setup(0, 0);
  viewport.stableHeight.set(800);
  assert.deepEqual(published, [800]);
});

test('zero is not a height: the 100dvh fallback stays until there is one', (t) => {
  t.after(() => mock.timers.reset());
  const { viewport, published } = setup(0, 0);
  viewport.height.set(0);
  mock.timers.tick(SETTLE_MS);
  assert.deepEqual(published, []);
});

test('a drag does not move the app on every frame', (t) => {
  t.after(() => mock.timers.reset());
  const { viewport, published } = setup(800, 800);
  published.length = 0;
  for (const height of [780, 760, 740]) {
    viewport.height.set(height);
    mock.timers.tick(SETTLE_MS / 4);
  }
  assert.deepEqual(published, []);
  mock.timers.tick(SETTLE_MS);
  assert.deepEqual(published, [740]);
});

test('a height Telegram already had is published at once', (t) => {
  t.after(() => mock.timers.reset());
  assert.deepEqual(setup(800, 800).published, [800]);
});

// Dragged, held, let go: the sheet springs back to the stable height it had,
// so the stable signal does not move and only the live one says so.
test('a sheet that springs back is its full height again without waiting', (t) => {
  t.after(() => mock.timers.reset());
  const { viewport, published } = setup(800, 800);
  viewport.height.set(600);
  mock.timers.tick(SETTLE_MS);
  viewport.height.set(800);
  assert.equal(published.at(-1), 800);
});

test('expanded after minimising, the app takes the height it settled at', (t) => {
  t.after(() => mock.timers.reset());
  const { viewport, published } = setup(800, 800);
  viewport.height.set(96);
  viewport.stableHeight.set(96);
  mock.timers.tick(SETTLE_MS);

  viewport.height.set(500);
  viewport.height.set(800);
  mock.timers.tick(SETTLE_MS);

  assert.equal(published.at(-1), 800);
});

test('stopping cancels a height still settling', (t) => {
  t.after(() => mock.timers.reset());
  const { viewport, published, stop } = setup(800, 800);
  published.length = 0;
  viewport.height.set(600);
  stop();
  mock.timers.tick(SETTLE_MS);
  viewport.stableHeight.set(500);
  assert.deepEqual(published, []);
});
