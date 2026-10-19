/*
 * The interface speaks plain language in every catalog.
 *
 * Students type «матан» and «přijímačky», and the search keeps understanding
 * them. The screens do not say them back: a placeholder or a chip in slang is
 * the product talking a register some readers do not know. The list is the one
 * the catalog and the bot are held to (`catalog/tests/test_plain_language.py`,
 * `tests/plain_language.py`) — the words that have actually shipped and their
 * obvious neighbours.
 *
 * Read from the .po files rather than the sources, because the translations are
 * where most of the text is, and both the source string (`msgid`, Russian) and
 * every translation (`msgstr`) are checked, obsolete entries (`#~`) among
 * them: Lingui compiles those into the bundle as well.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const LOCALES = ['ru', 'cs', 'en', 'uk'];

// `\b` is ASCII-only in JavaScript, so a word start is "no letter before".
const SLANG = new RegExp(
  '(?<![\\p{L}\\p{N}_])(' +
    'матан|матеш|линал|англ(?![\\p{L}])|шари(шь|т|те|ть)(?![\\p{L}])|теорвер|дискрет(к|ок)|сопромат|общаг' +
    '|при[её]м(к|ок)|приймач(к|ок)|přijímač(k|ek)|matan|matik(a|o|u|y|ou)(?![\\p{L}])|sopromat|vejš(k|c)' +
    ')',
  'giu',
);

function slang(text: string): string[] {
  return [...text.normalize('NFC').matchAll(SLANG)].map((match) => match[0]);
}

test('the list catches what it names and leaves plain words alone', () => {
  assert.deepEqual(slang('помощь по матану'), ['матан']);
  assert.deepEqual(slang('Přijímačky'), ['Přijímačk']);
  assert.deepEqual(slang('matika'), ['matika']);
  assert.deepEqual(slang('Čeština na vejšku'), ['vejšk']);
  assert.deepEqual(slang('na vejšce, bez přijímaček, matikou'), [
    'vejšc',
    'přijímaček',
    'matikou',
  ]);
  assert.deepEqual(slang('pr\u030cijímac\u030cky'), ['přijímačk']);
  assert.deepEqual(
    slang('Математический анализ, английский, Informatika, přijímací'),
    [],
  );
});

for (const locale of LOCALES) {
  test(`the ${locale} catalog has no slang`, () => {
    const path = new URL(`../src/locales/${locale}/messages.po`, import.meta.url);
    const found = readFileSync(path, 'utf8')
      .split('\n')
      .map((line, index) => ({ line: index + 1, text: line }))
      // Obsolete entries (`#~`) included: they are compiled into the bundle too.
      .filter(({ text }) => !text.startsWith('#:'))
      .flatMap(({ line, text }) => slang(text).map((word) => `${line}: ${word}`));
    assert.deepEqual(found, []);
  });
}

test('the page description has no slang', () => {
  // Outside the catalogs: search engines and link previews read it.
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.deepEqual(slang(html), []);
});
