import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

/**
 * The product is Konnekt: the chats and the help are one app now, and the old
 * name on a screen, in the tab title or in a first message says otherwise.
 * Storage keys are not a name anybody reads, and keep theirs.
 */

// The two words with anything markup puts between them: spaces, a no-break
// space as a character or an entity, JSX's {' '} (what the formatter writes
// when it wraps), and tags. Any case.
const OLD_NAME = /Students(?:\s|&nbsp;| |\{\s*['"`]\s*['"`]\s*\}|<[^>]*>)*CZ/i;

/** Every text file the build reads under src/. Generated code is not written here. */
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return entry === 'generated' ? [] : sources(path);
    return /\.(tsx?|jsx?|css|po|json|svg|html)$/.test(entry) ? [path] : [];
  });
}

test('the pattern catches the old name in the shapes it has had', () => {
  for (const shape of [
    'Students CZ',
    "Students{' '}\n  <span className={css.tail}>\n    CZ\n  </span>",
    'Students&nbsp;CZ',
    '<b>Students</b> <i>CZ</i>',
    'STUDENTS CZ',
  ]) {
    assert.match(shape, OLD_NAME, shape);
  }
});

test('no screen, stylesheet, catalog or first message says the old name', () => {
  const files = sources('src');
  // Reading nothing would pass too, and guard nothing.
  assert.ok(files.includes(join('src', 'pages', 'Landing.tsx')), 'the walk reads src/');
  const found = files.filter((path) => OLD_NAME.test(readFileSync(path, 'utf8')));
  assert.deepEqual(found, []);
});

test('the tab title says Konnekt', () => {
  const html = readFileSync('index.html', 'utf8');
  assert.match(html, /<title>Konnekt\b/);
  assert.doesNotMatch(html, OLD_NAME);
});
