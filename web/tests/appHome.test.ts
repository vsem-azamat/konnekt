import assert from 'node:assert/strict';
import { globSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

/*
 * The Mini App has a host of its own; the public site is konnekt.cz
 * (web/site/, docker/site/). The site hands a Telegram launch that lands on it
 * to the app's /home, and the app sends a browser, which it cannot serve, to
 * the site.
 */

const src = join(import.meta.dirname, '..', 'src');
const read = (file: string) => readFileSync(join(src, file), 'utf8');

test('the first screen is /home, and the root inside the app leads there', () => {
  const router = read('router.tsx');
  assert.match(router, /path: 'home', element: <HomePage \/>/);
  assert.match(router, /index: true, element: <Navigate to="\/home" replace \/>/);
});

test('an app opened at its root starts on /home with no history behind it', () => {
  // A <Navigate> would give the location a key, and the back button shows for
  // any key but the first: Home would open with a back button leading nowhere.
  const router = read('router.tsx');
  const rewrite = router.search(
    /history\.replaceState\(\s*window\.history\.state,\s*'',\s*`\/home/,
  );
  assert.ok(rewrite >= 0, 'the root is rewritten in place');
  assert.ok(
    rewrite < router.indexOf('createBrowserRouter(['),
    'before the router reads the location',
  );
});

test('the Help tab is lit on /home', () => {
  assert.match(read('components/TabBar.tsx'), /to: '\/home', icon: SearchIcon/);
});

test('a browser is sent to the site, the one the build names', () => {
  assert.equal(globSync('pages/Landing*', { cwd: src }).length, 0);
  const main = read('main.tsx');
  assert.doesNotMatch(main, /Landing/);
  assert.match(main, /window\.location\.replace\(site\)/);
  assert.match(main, /const site = import\.meta\.env\.VITE_SITE_URL/);
});
