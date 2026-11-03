import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

import { botEntry, siteEntry, siteRedirect } from '../src/lib/siteEntry.ts';

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

test('a browser stays only the third time in seconds: a loop, not a person opening twice', () => {
  // A loop is back within milliseconds, again and again; a person may open
  // the app's address a second time soon after being sent on.
  const session = tab();
  const at = (now: number) => siteRedirect('https://konnekt.cz', () => session, now);
  assert.equal(at(1_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(1_200), 'https://konnekt.cz/?from=app');
  assert.equal(at(1_400), null);
  assert.equal(at(1_000 + 9_999), null);
  assert.equal(at(1_200 + 10_000), 'https://konnekt.cz/?from=app');
});

test('two returns far apart are each sent on', () => {
  const session = tab();
  const at = (now: number) => siteRedirect('https://konnekt.cz', () => session, now);
  assert.equal(at(1_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(5_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(20_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(24_000), 'https://konnekt.cz/?from=app');
});

test('a clock set back does not keep the browser here', () => {
  const session = tab();
  const at = (now: number) => siteRedirect('https://konnekt.cz', () => session, now);
  assert.equal(at(3_600_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(3_600_100), 'https://konnekt.cz/?from=app');
  assert.equal(at(300_000), 'https://konnekt.cz/?from=app');
  assert.equal(at(300_100), 'https://konnekt.cz/?from=app');
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

test('the app sends a browser on through that, and keeps it when it is back at once', () => {
  const main = readFileSync(join(import.meta.dirname, '..', 'src', 'main.tsx'), 'utf8');
  assert.match(
    main,
    /siteRedirect\(site, \(\) => window\.sessionStorage, Date\.now\(\)\)/,
  );
  assert.doesNotMatch(main, /window\.location\.replace\(site\)/);
});

test('the way into the bot is the site’s, which knows the bot: no name here', () => {
  assert.equal(botEntry('https://konnekt.cz/'), 'https://konnekt.cz/api/v1/open?app=1');
});

test('a browser that stays is shown the app’s own screen, not a bare link', () => {
  const src = join(import.meta.dirname, '..', 'src');
  const main = readFileSync(join(src, 'main.tsx'), 'utf8');
  assert.match(main, /<OpenInTelegram site=\{site\} \/>/);
  assert.match(main, /else await renderOpenInTelegram\(site\)/);
  assert.match(main, /document\.title = 'Konnekt'/);
  assert.match(main, /document\.documentElement\.lang = locale;\n {2}document\.title/);
  assert.doesNotMatch(main, /showSiteLink|style\.cssText/);
  const screen = readFileSync(join(src, 'pages', 'OpenInTelegram.tsx'), 'utf8');
  assert.match(screen, /href=\{botEntry\(site\)\}/);
  assert.match(screen, /href=\{siteEntry\(site\)\}/);
  assert.match(screen, /Konnekt открывается в Telegram/);
  assert.match(screen, /Открыть Konnekt/);
  assert.match(screen, /На сайт/);
  assert.doesNotMatch(screen, /style=/);
});
