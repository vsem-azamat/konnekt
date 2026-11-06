/*
 * A translation is text in its own language, not data about several.
 *
 * #516 shipped, until review, a Python dict of three languages as the msgstr
 * of five entries: written by a script, accepted by `lingui extract` because
 * it was not empty, and shown whole on a button to anyone not reading Russian.
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

const TRANSLATED = ['cs', 'en', 'uk'];

test('no translation is a mapping of languages', () => {
  for (const locale of TRANSLATED) {
    const po = readFileSync(
      new URL(`../src/locales/${locale}/messages.po`, import.meta.url),
      'utf8',
    );
    const mappings = po
      .split('\n')
      .filter((line) => /^(#~ )?msgstr "\{\s*\\?["']/.test(line));
    assert.deepEqual(mappings, [], `${locale}: a msgstr holds a mapping`);
  }
});
