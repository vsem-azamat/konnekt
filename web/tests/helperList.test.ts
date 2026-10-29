/*
 * The helper list without tabs: one order chosen from a sheet, a search past
 * eight people, «добавь себя» under the list, and a sheet instead of an empty
 * list for a service nobody offers yet. Pinned in every catalogue, so a
 * language does not fall back to Russian on the screens that replaced the tabs.
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

const screens: Record<string, string[]> = {
  'src/pages/Results.tsx': [
    'Сначала показывать',
    'Подходят лучше',
    'Есть свободное время',
    'Имя или вуз',
    'Добавь себя в этот список — студенты напишут тебе сами.',
  ],
  'src/components/EmptyServiceSheet.tsx': [
    'Здесь пока никого',
    'Твоя анкета будет здесь первой.',
  ],
};

for (const locale of ['ru', 'cs', 'en', 'uk']) {
  test(`the helper list without tabs is translated in ${locale}`, () => {
    const path = new URL(`../src/locales/${locale}/messages.po`, import.meta.url);
    const po = readFileSync(path, 'utf8');
    for (const [source, ids] of Object.entries(screens)) {
      const entries = entriesFrom(po, source);
      for (const id of ids) {
        assert.ok(entries.has(id), `${id} is not in the ${locale} catalogue`);
        if (locale !== 'ru') {
          assert.notEqual(entries.get(id), '', `${id} is not translated in ${locale}`);
        }
      }
    }
  });
}

test('the tabs are gone from the results screen', () => {
  const page = readFileSync(new URL('../src/pages/Results.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(page, /Segmented/);
  assert.doesNotMatch(page, /params\.get\('v'\)/);
});
