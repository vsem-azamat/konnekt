import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import { siteEntry, siteRedirect } from '../src/lib/siteEntry.ts';

const tab = () => {
  const kept = new Map<string, string>();
  return {
    getItem: (key: string) => kept.get(key) ?? null,
    setItem: (key: string, value: string) => void kept.set(key, value),
  };
};

test('a browser is sent to an address of the site no old redirect is cached for', () => {
  // konnekt.cz/ once answered a permanent redirect to the app, and browsers
  // keep it: sent back to that same address, they would go round for ever.
  assert.equal(siteEntry('https://konnekt.cz'), 'https://konnekt.cz/?from=app');
  assert.equal(siteEntry('https://konnekt.cz/'), 'https://konnekt.cz/?from=app');
});

test('a browser back within seconds stays, one back later is sent on again', () => {
  // A loop returns within milliseconds; a person clicking the site's home
  // link, through a redirect their browser still keeps, takes seconds.
  const session = tab();
  const at = (now: number) => siteRedirect('https://konnekt.cz', () => session, now);
  assert.equal(at(1_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(1_200), null);
  assert.equal(at(1_000 + 9_999), null);
  assert.equal(at(1_000 + 10_000), 'https://konnekt.cz/?from=app');
  assert.equal(
    siteRedirect('https://konnekt.cz', tab, 1_200),
    'https://konnekt.cz/?from=app',
  );
});

test('a clock set back does not keep the browser here', () => {
  const session = tab();
  const at = (now: number) => siteRedirect('https://konnekt.cz', () => session, now);
  assert.equal(at(3_600_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(300_000), 'https://konnekt.cz/?from=app');
});

test('with no storage to remember in, the browser is still sent on', () => {
  const blocked = () => {
    throw new DOMException('denied', 'SecurityError');
  };
  assert.equal(
    siteRedirect('https://konnekt.cz', blocked, 0),
    'https://konnekt.cz/?from=app',
  );
});

test('the app sends a browser on through that, and shows the site when it stays', () => {
  const main = readFileSync(join(import.meta.dirname, '..', 'src', 'main.tsx'), 'utf8');
  assert.match(
    main,
    /siteRedirect\(site, \(\) => window\.sessionStorage, Date\.now\(\)\)/,
  );
  assert.match(main, /showSiteLink\(/);
  assert.doesNotMatch(main, /window\.location\.replace\(site\)/);
});
