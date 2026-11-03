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

test('a browser is sent on once per tab, and back again it stays', () => {
  const session = tab();
  assert.equal(
    siteRedirect('https://konnekt.cz', () => session),
    'https://konnekt.cz/?from=app',
  );
  assert.equal(
    siteRedirect('https://konnekt.cz', () => session),
    null,
  );
  assert.equal(siteRedirect('https://konnekt.cz', tab), 'https://konnekt.cz/?from=app');
});

test('with no storage to remember in, the browser is still sent on', () => {
  const blocked = () => {
    throw new DOMException('denied', 'SecurityError');
  };
  assert.equal(
    siteRedirect('https://konnekt.cz', blocked),
    'https://konnekt.cz/?from=app',
  );
});

test('the app sends a browser on through that, and shows the site when it stays', () => {
  const main = readFileSync(join(import.meta.dirname, '..', 'src', 'main.tsx'), 'utf8');
  assert.match(main, /siteRedirect\(site, \(\) => window\.sessionStorage\)/);
  assert.match(main, /showSiteLink\(/);
  assert.doesNotMatch(main, /window\.location\.replace\(site\)/);
});
