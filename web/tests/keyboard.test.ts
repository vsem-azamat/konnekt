import assert from 'node:assert/strict';
import { test } from 'node:test';

import { followKeyboard } from '../src/lib/keyboard.ts';

/** `window.visualViewport` as far as the rule reads it, and a window of `layout` px. */
function setup(layout = 844) {
  const view = Object.assign(new EventTarget(), { height: layout, offsetTop: 0 });
  const window = { innerHeight: layout };
  const published: [number, number][] = [];
  const stop = followKeyboard(
    view,
    () => window.innerHeight,
    (cover) => published.push([cover.covered, cover.panned]),
  );
  const move = (height: number, offsetTop = 0) => {
    view.height = height;
    view.offsetTop = offsetTop;
    view.dispatchEvent(new Event('resize'));
  };
  return { view, window, published, stop, move };
}

test('the iOS keyboard covers what the visual viewport lost', () => {
  const { published, move } = setup(844);
  move(508);
  assert.deepEqual(published, [[336, 0]]);
});

test('panned down to the field, the view has left the top of the layout behind', () => {
  const { published, move } = setup(844);
  move(508, 100);
  assert.deepEqual(published, [[236, 100]]);
});

test('the keyboard going down uncovers the bottom again', () => {
  const { published, move } = setup(844);
  move(508);
  move(844);
  assert.deepEqual(published, [
    [336, 0],
    [0, 0],
  ]);
});

test('Android resizes the whole webview, which covers nothing', () => {
  const { window, published, move } = setup(640);
  window.innerHeight = 380;
  move(380);
  assert.deepEqual(published, []);
});

test('the same cover is not published twice', () => {
  const { view, published, move } = setup(844);
  move(508);
  view.dispatchEvent(new Event('scroll'));
  assert.deepEqual(published, [[336, 0]]);
});

test('stopped, it publishes nothing more', () => {
  const { published, move, stop } = setup(844);
  stop();
  move(508);
  assert.deepEqual(published, []);
});
