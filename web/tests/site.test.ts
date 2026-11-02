import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  alternates,
  guidePath,
  hiddenPaths,
  langOf,
  localePath,
  telegramHome,
} from '../site/src/paths.ts';

test('Russian lives at the root, the other languages under their prefix', () => {
  assert.equal(localePath('ru', '/'), '/');
  assert.equal(localePath('uk', '/'), '/uk/');
  assert.equal(localePath('cs', '/guides/'), '/cs/guides/');
  assert.equal(localePath('en', '/guides/visa/'), '/en/guides/visa/');
});

test('a guide is addressed by its language and slug', () => {
  assert.equal(guidePath('ru/visa'), '/guides/visa/');
  assert.equal(guidePath('cs/visa'), '/cs/guides/visa/');
  assert.equal(langOf('uk/visa'), 'uk');
});

test('hreflang names every translation, and Russian as the default', () => {
  assert.deepEqual(alternates('/guides/visa/', ['ru', 'cs'], 'https://konnekt.cz'), [
    { hreflang: 'ru', href: 'https://konnekt.cz/guides/visa/' },
    { hreflang: 'cs', href: 'https://konnekt.cz/cs/guides/visa/' },
    { hreflang: 'x-default', href: 'https://konnekt.cz/guides/visa/' },
  ]);
});

test('a page with no Russian version has no default to point at', () => {
  assert.deepEqual(alternates('/guides/x/', ['en'], 'https://konnekt.cz/'), [
    { hreflang: 'en', href: 'https://konnekt.cz/en/guides/x/' },
  ]);
});

test('the landing hands Telegram back to the app, launch data and all', () => {
  const data = '#tgWebAppData=user%3D1&tgWebAppVersion=8.0';
  assert.equal(telegramHome(data, ''), `/home${data}`);
  assert.equal(telegramHome(data, '?x=1'), `/home?x=1${data}`);
});

test('a browser stays on the landing', () => {
  assert.equal(telegramHome('', ''), null);
  assert.equal(telegramHome('#guides', '?q=1'), null);
});

test('draft guides and an index with no published guide are kept out of search', () => {
  const guides = [
    { id: 'ru/primer', draft: true },
    { id: 'ru/visa', draft: false },
    { id: 'cs/primer', draft: true },
  ];
  assert.deepEqual(hiddenPaths(guides).sort(), [
    '/cs/guides/',
    '/cs/guides/primer/',
    '/en/guides/',
    '/guides/primer/',
    '/uk/guides/',
  ]);
});
