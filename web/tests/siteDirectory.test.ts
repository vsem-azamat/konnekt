import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  articlesAbout,
  checkPlaces,
  facultyChats,
  facultyCode,
  movedFrom,
  placeIndexable,
  placeOf,
  universityAddress,
  universityCode,
  universityPath,
} from '../site/src/catalog/directory.ts';
import type { PublicChat } from '../src/lib/chats.ts';

const chat = (title: string, link: string): PublicChat => ({
  title,
  link,
  group: 'ČVUT',
  institution: 'cvut',
  activity: 'unknown',
  member_count: 985,
  is_forum: false,
  kind: 'group',
  external: false,
  avatar: null,
  city: 'Praha',
  topic: 'university',
});

test('Charles University lives at cuni, and its old address points there', () => {
  assert.equal(universityAddress('uk'), 'cuni');
  assert.equal(universityAddress('cvut'), 'cvut');
  assert.equal(universityPath('uk', 'uk'), '/uk/universities/cuni/');
  assert.equal(universityPath('ru', 'cvut'), '/universities/cvut/');
  assert.equal(universityCode('cuni'), 'uk');
  assert.equal(universityCode('cvut'), 'cvut');
  // The old address is no university's: it is answered with a redirect.
  assert.equal(universityCode('uk'), null);
  assert.equal(movedFrom('uk'), 'cuni');
  assert.equal(movedFrom('cvut'), null);
  assert.equal(universityCode('CVUT'), null);
  assert.equal(universityCode('../x'), null);
});

test('a faculty’s code is its university’s and its own address', () => {
  assert.equal(facultyCode('cvut', 'fit'), 'cvut_fit');
  assert.equal(facultyCode('uk', '1lf'), 'uk_1lf');
});

test('a text’s place is its file’s path', () => {
  assert.deepEqual(placeOf('ru/cvut'), {
    lang: 'ru',
    university: 'cvut',
    faculty: null,
    address: 'cvut',
  });
  assert.deepEqual(placeOf('en/cvut/fit'), {
    lang: 'en',
    university: 'cvut',
    faculty: 'fit',
    address: 'cvut/fit',
  });
  assert.throws(() => placeOf('de/cvut'), /expected/);
  assert.throws(() => placeOf('ru/cvut/fit/x'), /expected/);
  // Charles University's text goes under its address, not its code.
  assert.throws(() => placeOf('ru/uk'), /lives at cuni/);
});

test('a page with our text is indexed whatever its chats; one without, by its chats', () => {
  assert.equal(placeIndexable(true, 0), true);
  assert.equal(placeIndexable(true, null), true);
  assert.equal(placeIndexable(false, 2), true);
  assert.equal(placeIndexable(false, 1), false);
  assert.equal(placeIndexable(false, null), false);
});

test('an article names only pages that have a text in its language', () => {
  const texts = new Set(['ru/cvut', 'ru/cvut/fit', 'uk/cvut']);
  checkPlaces({ id: 'ru/postuplenie', universities: ['cvut', 'cvut/fit'] }, texts);
  checkPlaces({ id: 'ru/vize' }, texts);
  assert.throws(
    () => checkPlaces({ id: 'uk/vstup', universities: ['cvut/fit'] }, texts),
    /uk\/vstup: universities names cvut\/fit/,
  );
  assert.throws(
    () => checkPlaces({ id: 'ru/x', universities: ['cvut_fit'] }, texts),
    /names cvut_fit/,
  );
});

test('a university lists the articles about it and its faculties; a faculty, its own', () => {
  const articles = [
    { id: 'a', universities: ['cvut'] },
    { id: 'b', universities: ['cvut/fit'] },
    { id: 'c', universities: ['cvut-x'] },
    { id: 'd' },
  ];
  const ids = (list: { id: string }[]) => list.map((a) => a.id);
  assert.deepEqual(ids(articlesAbout(articles, { address: 'cvut', faculty: null })), [
    'a',
    'b',
  ]);
  assert.deepEqual(
    ids(articlesAbout(articles, { address: 'cvut/fit', faculty: 'fit' })),
    ['b'],
  );
});

test('a faculty’s chats are found by link, however the link is written', () => {
  const fit = chat('ČVUT FIT', 'https://t.me/cvut_fit');
  const found = facultyChats(
    ['https://telegram.me/CVUT_FIT/', 'https://t.me/gone'],
    [fit, chat('ČVUT FEL', 'https://t.me/cvut_fel')],
  );
  assert.deepEqual(found, [{ chat: fit }, { link: 'https://t.me/gone' }]);
  // Without the catalogue, every chat is its link.
  assert.deepEqual(facultyChats(['https://t.me/cvut_fit'], null), [
    { link: 'https://t.me/cvut_fit' },
  ]);
});
