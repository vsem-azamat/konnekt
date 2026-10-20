import assert from 'node:assert/strict';
import { test } from 'node:test';

import { focusInto, giveFocusBack } from '../src/components/sheetFocus.ts';

function fake(connected = true) {
  const calls: unknown[] = [];
  return {
    calls,
    isConnected: connected,
    focus: (options?: unknown) => {
      calls.push(options ?? 'plain');
    },
  };
}

test('a sheet takes focus when it opens, without scrolling the page under it', () => {
  const panel = fake();
  focusInto(panel);
  assert.deepEqual(panel.calls, [{ preventScroll: true }]);
});

test('a sheet that is not mounted yet takes nothing', () => {
  assert.doesNotThrow(() => focusInto(null));
});

test('closing returns focus to what opened the sheet', () => {
  const opener = fake();
  giveFocusBack(opener);
  assert.deepEqual(opener.calls, [{ preventScroll: true }]);
});

test('what opened the sheet may be gone by the time it closes, and focus is left alone', () => {
  // A choice in the sheet can remove its own button: focusing a detached node
  // does nothing, and would hide that nothing happened.
  const opener = fake(false);
  giveFocusBack(opener);
  assert.deepEqual(opener.calls, []);
});

test('nothing was focused before the sheet opened, so nothing is given back', () => {
  assert.doesNotThrow(() => giveFocusBack(null));
});
