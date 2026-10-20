import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { chatPreview } from '../src/lib/chatPreview.ts';

const FIT = 'https://t.me/cvut_fit';
const HERE = { pathname: '/chats', search: '?x=1', hash: '', state: null };

/** Records what the preview asked of the router and of Telegram, in order. */
function harness(state: unknown = null) {
  const calls: unknown[][] = [];
  const preview = chatPreview(
    FIT,
    { ...HERE, state },
    {
      navigate: (...args: unknown[]) => calls.push(['navigate', ...args]),
      openLink: (link: string) => calls.push(['openLink', link]),
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
