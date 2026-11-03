import assert from 'node:assert/strict';
import { test } from 'node:test';

import { articleSource, num, openLink, phone, t, v } from '../site/src/landing/copy.ts';
import { COPY, STATS } from '../site/src/landing/data.ts';

test('a number reads the way its language writes it, with no line break inside', () => {
  // A narrow no-break space, as the prototype wrote them.
  assert.equal(num('ru', 14141), '14\u202f141');
  assert.equal(num('cs', 14141), '14\u202f141');
  assert.equal(num('en', 14141), '14,141');
});

test('the copy fills the numbers it names', () => {
  assert.equal(
    t('ru', 'stats.students'),
    `участников в ${STATS.botChats} чатах с Konnekt`,
  );
});

test('every language has every word Russian has', () => {
  for (const lang of ['uk', 'cs', 'en'] as const) {
    assert.deepEqual(Object.keys(COPY[lang]).sort(), Object.keys(COPY.ru).sort(), lang);
  }
});

test('a missing key is loud, not a blank on the page', () => {
  assert.throws(() => t('ru', 'no.such.key'));
  assert.throws(() => v('ru', 'noSuchKey'));
});

test('the phone shows the app in the page language', () => {
  assert.match(phone('cs'), /Co potřebuješ\?/);
  assert.match(phone('cs'), /<span class="am-pill">CS<\/span>/);
});

test('each way into the app says which button it was, in a shape the catalog passes on', () => {
  assert.equal(openLink('site_header'), '/api/v1/open?app=1&from=site_header');
  assert.equal(
    articleSource('nostrifikaciya-attestata'),
    'site_article_nostrifikaciya-attestata',
  );
  // Telegram takes 64 characters of a start parameter; a long slug is cut, not refused.
  const long = articleSource('x'.repeat(80));
  assert.equal(long.length, 64);
  assert.match(long, /^site_[a-z0-9][a-z0-9_-]{0,58}$/);
});
