import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { chatPreview } from '../src/lib/chatPreview.ts';

const FIT = 'https://t.me/cvut_fit';
const HERE = { pathname: '/chats', search: '?x=1', hash: '', state: null, key: 'k1' };

/** Records what the preview asked of the router and of Telegram, in order. */
function harness(state: unknown = null, key = HERE.key, now: unknown = state) {
  const calls: unknown[][] = [];
  const preview = chatPreview(
    FIT,
    { ...HERE, state, key },
    {
      navigate: (...args: unknown[]) => calls.push(['navigate', ...args]),
      openLink: (link: string) => calls.push(['openLink', link]),
      stateNow: () => now,
    },
  );
  return { preview, calls };
}

test('a tap opens the preview as a history entry, so Back closes it', () => {
  const { preview, calls } = harness();
  preview.show();
  assert.deepEqual(calls, [
    [
      'navigate',
      { pathname: '/chats', search: '?x=1', hash: '' },
      { state: { preview: FIT } },
    ],
  ]);
});

test('a tap never leaves for Telegram', () => {
  const { preview, calls } = harness();
  preview.show();
  assert.equal(
    calls.some(([kind]) => kind === 'openLink'),
    false,
  );
});

test('a second tap on an open preview adds nothing, so one Back still closes it', () => {
  // A double tap, or Enter twice, lands both events before the sheet renders.
  const { preview, calls } = harness({ preview: FIT });
  preview.show();
  assert.deepEqual(calls, []);
  // The second of two taps in one frame: rendered closed, already open in history.
  const late = harness(null, HERE.key, { preview: FIT });
  late.preview.show();
  assert.deepEqual(late.calls, []);
});

test('opened straight from a link, closing stays on the page instead of leaving the app', () => {
  // No entry behind this one: going back would close the Mini App.
  const closed = harness({ preview: FIT }, 'default');
  closed.preview.close();
  const joined = harness({ preview: FIT }, 'default');
  joined.preview.join();
  const replace = [
    'navigate',
    { pathname: '/chats', search: '?x=1', hash: '' },
    { replace: true, state: null },
  ];
  assert.deepEqual(closed.calls, [replace]);
  assert.deepEqual(joined.calls, [replace, ['openLink', FIT]]);
});

test('the preview is open only for the chat the entry names', () => {
  assert.equal(harness({ preview: FIT }).preview.open, true);
  assert.equal(harness({ preview: 'https://t.me/other' }).preview.open, false);
  assert.equal(harness(null).preview.open, false);
  assert.equal(harness('garbage').preview.open, false);
});

test('closing goes back rather than forward, so the entry is not left behind', () => {
  const { preview, calls } = harness({ preview: FIT });
  preview.close();
  assert.deepEqual(calls, [['navigate', -1]]);
});

test('«Открыть чат» takes the preview off the history first, then opens the chat', () => {
  const { preview, calls } = harness({ preview: FIT });
  preview.join();
  assert.deepEqual(calls, [
    ['navigate', -1],
    ['openLink', FIT],
  ]);
});

test('ChatRow reaches Telegram only through the preview', () => {
  // The row's tap is `show`, which the tests above prove opens nothing. The
  // one way to Telegram is the link handed to the preview, which only `join`,
  // the sheet's button, calls.
  const source = readFileSync(
    new URL('../src/components/ChatRow.tsx', import.meta.url),
    'utf8',
  );
  const uses = source.match(/openTelegramLink/g) ?? [];
  assert.equal(uses.length, 2, 'imported once and handed to chatPreview once');
  assert.match(source, /openLink: openTelegramLink/);
  assert.match(
    source,
    /onClick=\{\(\) => \{\s*hapticSelection\(\);\s*preview\.show\(\);/,
  );
  assert.match(source, /onJoin=\{preview\.join\}/);
  assert.match(source, /<Action onClick=\{onJoin\}>/);
});
