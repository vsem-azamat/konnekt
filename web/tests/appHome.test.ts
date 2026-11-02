import assert from 'node:assert/strict';
import { globSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

/*
 * The site's landing page owns the root of the domain (site/, docker/Caddyfile),
 * so the Mini App's first screen is /home. A link, navigation or reload aimed
 * at / from inside the app would leave it for the landing page.
 */

const src = join(import.meta.dirname, '..', 'src');
const read = (file: string) => readFileSync(join(src, file), 'utf8');

test('no screen sends the app to the root', () => {
  // main.tsx is the exception, and the point: it sends a browser to the site.
  const screens = globSync('**/*.{ts,tsx}', { cwd: src }).filter(
    (file) => file !== 'main.tsx',
  );
  const offenders = screens.filter((file) =>
    /(?:navigate|assign|replace)\(\s*(?:[^)]*\?\s*'[^']*'\s*:\s*)?'\/'|to: '\/'|to="\/"/.test(
      read(file),
    ),
  );
  assert.deepEqual(offenders, []);
});

test('the first screen is /home, and the root inside the app leads there', () => {
  const router = read('router.tsx');
  assert.match(router, /path: 'home', element: <HomePage \/>/);
  assert.match(router, /index: true, element: <Navigate to="\/home" replace \/>/);
});

test('the Help tab is lit on /home', () => {
  assert.match(read('components/TabBar.tsx'), /to: '\/home', icon: SearchIcon/);
});

test('a browser gets the site rather than a landing page of the app', () => {
  assert.equal(globSync('pages/Landing*', { cwd: src }).length, 0);
  assert.doesNotMatch(read('main.tsx'), /Landing/);
});
