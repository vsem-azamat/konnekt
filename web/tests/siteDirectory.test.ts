import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  articlesAbout,
  checkPlaces,
  facultyAddress,
  facultyChats,
  facultyList,
  movedFrom,
  placeIndexable,
  placeOf,
  universityAddress,
  universityCode,
  universityLangs,
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

test('an address named like an object’s own property is no university and no redirect', () => {
  for (const address of ['constructor', 'toString', 'hasOwnProperty', '__proto__']) {
    assert.equal(movedFrom(address), null, address);
    assert.equal(universityAddress(address), address, address);
  }
  assert.equal(universityCode('constructor'), 'constructor');
  assert.equal(universityCode('__proto__'), null);
});

test('a university’s page names as its versions only the ones search keeps', () => {
  // Enough chats: a page in every language.
  assert.deepEqual(universityLangs('ru', ['ru'], 2), ['ru', 'uk', 'cs', 'en']);
  // Fewer: the languages of its text alone.
  assert.deepEqual(universityLangs('ru', ['ru'], 1), ['ru']);
  assert.deepEqual(universityLangs('ru', ['ru', 'uk'], 0), ['ru', 'uk']);
  assert.deepEqual(universityLangs('uk', ['ru', 'uk'], null), ['ru', 'uk']);
  // A page search does not keep names them all, as before the directory.
  assert.deepEqual(universityLangs('en', ['ru'], 1), ['ru', 'uk', 'cs', 'en']);
});

test('a faculty’s address is its code without its university’s', () => {
  assert.equal(facultyAddress('cvut', 'cvut_fit'), 'fit');
  assert.equal(facultyAddress('uk', 'uk_1lf'), '1lf');
  assert.equal(facultyAddress('mendelu', 'mendelu_zahr_fak'), 'zahr-fak');
  assert.equal(facultyAddress('cvut', 'vse_fis'), null);
  assert.equal(facultyAddress('cvut', 'cvut_'), null);
});

test('a university lists every faculty the catalog has, with a page where there is a text', () => {
  const texts = [
    { faculty: 'fit', name: 'ФИТ ЧВУТ (FIT)', short: 'FIT', chats: 2 },
    // A text for a faculty the catalog does not list (yet): still its page.
    { faculty: 'masaryk', name: 'Институт Масарика', short: 'MÚVS', chats: 0 },
  ];
  const catalog = [
    { code: 'cvut_fsv', name: 'Строительный факультет', short_name: 'FSv' },
    { code: 'cvut_fit', name: 'Факультет информационных технологий', short_name: 'FIT' },
    { code: 'cvut_fd', name: 'Транспортный факультет', short_name: null },
  ];
  assert.deepEqual(facultyList('cvut', catalog, texts), [
    {
      faculty: 'fsv',
      name: 'Строительный факультет',
      short: 'FSv',
      chats: 0,
      page: false,
    },
    {
      faculty: 'fit',
      name: 'Факультет информационных технологий',
      short: 'FIT',
      chats: 2,
      page: true,
    },
    { faculty: 'fd', name: 'Транспортный факультет', short: 'FD', chats: 0, page: false },
    {
      faculty: 'masaryk',
      name: 'Институт Масарика',
      short: 'MÚVS',
      chats: 0,
      page: true,
    },
  ]);
  // Without the catalog (down, or a university it does not list): the texts alone.
  assert.deepEqual(
    facultyList('cvut', null, texts).map((card) => [card.faculty, card.page]),
    [
      ['fit', true],
      ['masaryk', true],
    ],
  );
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
  const texts = new Map([
    ['ru/cvut', false],
    ['ru/cvut/fit', false],
    ['uk/cvut', false],
    ['ru/cvut/fel', true],
  ]);
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
  // A draft text: a draft article may name it, a published one not yet.
  checkPlaces({ id: 'ru/x', draft: true, universities: ['cvut/fel'] }, texts);
  assert.throws(
    () => checkPlaces({ id: 'ru/x', universities: ['cvut/fel'] }, texts),
    /still a draft/,
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
    [
      chat('ČVUT', 'https://t.me/cvut_chat'),
      fit,
      chat('ČVUT FEL', 'https://t.me/cvut_fel'),
    ],
  );
  assert.deepEqual(found.chats, [{ chat: fit }, { link: 'https://t.me/gone' }]);
  // Without the catalogue, every chat is its link, and there is no main chat.
  assert.deepEqual(facultyChats(['https://t.me/cvut_fit'], null), {
    chats: [{ link: 'https://t.me/cvut_fit' }],
    universityChat: null,
  });
});

test('a faculty’s chats show each chat once, the university’s main chat as its own row', () => {
  // The university's own room: titled as its group.
  const main = chat('ČVUT', 'https://t.me/cvut_chat');
  const fit = chat('ČVUT FIT', 'https://t.me/cvut_fit');
  const found = facultyChats(
    ['https://t.me/cvut_fit', 'https://t.me/CVUT_CHAT/', 'https://telegram.me/cvut_fit'],
    [main, fit],
  );
  assert.deepEqual(found, { chats: [{ chat: fit }], universityChat: main });
});
