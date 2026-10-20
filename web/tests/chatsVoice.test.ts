/*
 * The chat catalogue speaks as the video does: what happens to spam, not who
 * does it. «Модерируются» was the bot's old line too, and the bot's own texts
 * changed in the same PR (#264). Only the catalogue screen is held to it here;
 * the console, which only operators open, talks about moderators by design.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const SAID_OF_CHATS = /модер|moderat|moderov/i;

/** Every msgid/msgstr line of the entries that come from one source file. */
function linesFrom(po: string, source: string): string[] {
  return po
    .split('\n\n')
    .filter((entry) =>
      entry.split('\n').some((line) => line.startsWith('#:') && line.includes(source)),
    )
    .flatMap((entry) => entry.split('\n').filter((line) => !line.startsWith('#')));
}

for (const locale of ['ru', 'cs', 'en', 'uk']) {
  test(`the ${locale} chat catalogue does not say the chats are moderated`, () => {
    const path = new URL(`../src/locales/${locale}/messages.po`, import.meta.url);
    const lines = linesFrom(readFileSync(path, 'utf8'), 'src/pages/Chats.tsx');
    assert.ok(lines.length > 0, 'no entries from Chats.tsx — did the file move?');
    assert.deepEqual(
      lines.filter((line) => SAID_OF_CHATS.test(line)),
      [],
    );
  });
}
