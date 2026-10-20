/*
 * The Profile tab offers the way to reach Konnekt about anything: the same
 * contact as the ads pages, presented as «Написать нам», not as advertising.
 * Pinned in every catalogue, so a language does not fall back to Russian.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

/** msgid → msgstr of the entries that come from one source file. */
function entriesFrom(po: string, source: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const entry of po.split('\n\n')) {
    const lines = entry.split('\n');
    if (!lines.some((line) => line.startsWith('#:') && line.includes(source))) continue;
    const id = lines.find((line) => line.startsWith('msgid '))?.slice(7, -1);
    const str = lines.find((line) => line.startsWith('msgstr '))?.slice(8, -1);
    if (id !== undefined && str !== undefined) found.set(id, str);
  }
  return found;
}

for (const locale of ['ru', 'cs', 'en', 'uk']) {
  test(`Profile offers «Написать нам» for any question in ${locale}`, () => {
    const path = new URL(`../src/locales/${locale}/messages.po`, import.meta.url);
    const entries = entriesFrom(readFileSync(path, 'utf8'), 'src/pages/Profile.tsx');
    for (const id of ['Написать нам', 'по любому вопросу']) {
      assert.ok(entries.has(id), `${id} is not in the ${locale} catalogue`);
      assert.notEqual(entries.get(id), '', `${id} is not translated in ${locale}`);
    }
  });
}
