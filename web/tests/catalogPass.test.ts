import assert from 'node:assert/strict';
import { test } from 'node:test';

import { joinFromCatalog } from '../src/lib/catalogPass.ts';

const LINK = 'https://t.me/cvut_fit';

function harness(opts: {
  initData?: string;
  external?: boolean;
  claim?: () => Promise<unknown>;
}) {
  const calls: unknown[][] = [];
  joinFromCatalog(
    { link: LINK, external: opts.external ?? false },
    {
      initData: () => opts.initData,
      claim:
        opts.claim ??
        ((raw, link) => {
          calls.push(['claim', raw, link]);
          return Promise.resolve();
        }),
      openLink: (link) => calls.push(['openLink', link]),
    },
  );
  return calls;
}

test('the pass is claimed first, then the link opens', () => {
  assert.deepEqual(harness({ initData: 'signed' }), [
    ['claim', 'signed', LINK],
    ['openLink', LINK],
  ]);
});

test('a chat we do not run asks for no pass', () => {
  assert.deepEqual(harness({ initData: 'signed', external: true }), [['openLink', LINK]]);
});

test('without initData the link still opens', () => {
  assert.deepEqual(harness({}), [['openLink', LINK]]);
});

test('a failing claim does not stop the link', async () => {
  const calls = harness({
    initData: 'signed',
    claim: () => Promise.reject(new Error('down')),
  });
  assert.deepEqual(calls, [['openLink', LINK]]);
  await new Promise((resolve) => setTimeout(resolve, 0));
});

test('a claim that throws at once does not stop the link', () => {
  const calls = harness({
    initData: 'signed',
    claim: () => {
      throw new Error('boom');
    },
  });
  assert.deepEqual(calls, [['openLink', LINK]]);
});
