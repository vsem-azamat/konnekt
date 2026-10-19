import assert from 'node:assert/strict';
import { test } from 'node:test';

import { cities, type PublicChat, search } from '../src/lib/chats.ts';
import { find, matches } from '../src/lib/search.ts';

function chat(
  title: string,
  group: string | null,
  institution: string | null = null,
): PublicChat {
  return {
    title,
    link: `https://t.me/${title.replace(/\W+/g, '_').toLowerCase()}`,
    group,
    institution,
    activity: 'active',
  };
}

const UK = 'Karlova univerzita | Карлов университет';
const CVUT = 'ČVUT | ЧВУТ';

// The directory as supervisor serves it, titles and groups unchanged.
const DIRECTORY: PublicChat[] = [
  chat(UK, UK, 'uk'),
  chat('Matfyz | Karlova univerzita', UK, 'uk'),
  chat('Masarykova univerzita', 'Masarykova univerzita', 'muni'),
  chat('VUT', 'VUT', 'vut'),
  chat('VŠCHT', 'VŠCHT', 'vscht'),
  chat(CVUT, CVUT, 'cvut'),
  chat('ČVUT FEL', CVUT, 'cvut'),
  chat('ČVUT FIT', CVUT, 'cvut'),
  chat('Fyzika v ČR', null),
  // A group with no university behind it: found by its group alone.
  chat('Olympiáda', 'Fyzika v ČR'),
  chat('IT Чехия | Опыт, работа, новости', null),
  chat('Kolej Hvězda', null, 'cvut'),
  chat('Strahov', null, 'cvut'),
  chat('VŠE', null, 'vse'),
];

// The universities' cities, as the catalog's taxonomy gives them.
const CITIES = cities([
  { code: 'uk', city: 'Praha' },
  { code: 'cvut', city: 'Praha' },
  { code: 'vse', city: 'Praha' },
  { code: 'vscht', city: 'Praha' },
  { code: 'muni', city: 'Brno' },
  { code: 'vut', city: 'Brno' },
  { code: 'zcu', city: null },
]);

function titles(query: string): string[] {
  return search(DIRECTORY, query, CITIES).map((c) => c.title);
}

const CVUT_CHATS = [CVUT, 'ČVUT FEL', 'ČVUT FIT', 'Kolej Hvězda', 'Strahov'];

test('ČVUT is found in either script, any case, with or without the háček', () => {
  for (const query of ['чвут', 'ЧВУТ', 'cvut', 'CVUT', 'ČVUT', 'čvut']) {
    assert.deepEqual(titles(query), CVUT_CHATS, query);
  }
});

test('VŠE is found in either script', () => {
  for (const query of ['вше', 'ВШЕ', 'vse', 'VSE', 'VŠE']) {
    assert.deepEqual(titles(query), ['VŠE'], query);
  }
});

test('faculty and university abbreviations work in Cyrillic', () => {
  assert.deepEqual(titles('фит'), ['ČVUT FIT']);
  assert.deepEqual(titles('fit'), ['ČVUT FIT']);
  assert.deepEqual(titles('муни'), ['Masarykova univerzita']);
  assert.deepEqual(titles('muni'), ['Masarykova univerzita']);
  assert.deepEqual(titles('вут'), ['VUT']);
  assert.deepEqual(titles('vut'), ['VUT']);
});

test('one university is not another that contains its letters', () => {
  assert.ok(!titles('чвут').includes('VŠE'));
  assert.ok(!titles('вше').includes('VŠCHT'));
  // «vut» sits inside «cvut»: a word has to start with what was typed.
  assert.ok(!titles('вут').some((title) => title.includes('ČVUT')));
  assert.ok(!titles('vut').some((title) => title.includes('ČVUT')));
});

test('the colloquial Russian names reach the chats', () => {
  assert.deepEqual(titles('карлов'), [UK, 'Matfyz | Karlova univerzita']);
  assert.deepEqual(titles('карлова'), [UK, 'Matfyz | Karlova univerzita']);
  assert.deepEqual(titles('uk'), [UK, 'Matfyz | Karlova univerzita']);
  assert.deepEqual(titles('масарик'), ['Masarykova univerzita']);
  assert.deepEqual(titles('страгов'), ['Strahov']);
  assert.deepEqual(titles('хвезда'), ['Kolej Hvězda']);
  assert.deepEqual(titles('матфиз'), ['Matfyz | Karlova univerzita']);
  assert.deepEqual(titles('физика'), ['Fyzika v ČR', 'Olympiáda']);
});

test('they match as spelled, not by way of a typo', () => {
  // y and i, h and г, h and х are one letter here; without that, these would
  // only be found by the typo allowance, and «матфис» not at all.
  assert.ok(matches(['Masarykova univerzita'], 'масарик', false));
  assert.ok(matches(['Matfyz'], 'матфиз', false));
  assert.ok(matches(['Fyzika v ČR'], 'физика', false));
  assert.ok(matches(['Strahov'], 'страгов', false));
  assert.ok(matches(['Kolej Hvězda'], 'хвезда', false));
  assert.deepEqual(titles('матфис'), ['Matfyz | Karlova univerzita']);
});

test('a chat in a group without a university is found by the group', () => {
  assert.deepEqual(titles('олимпиада физика'), ['Olympiáda']);
});

test('a city finds the chats of its universities', () => {
  assert.deepEqual(titles('брно'), ['Masarykova univerzita', 'VUT']);
  assert.deepEqual(titles('brno vut'), ['VUT']);
  assert.ok(titles('прага').includes('Strahov'));
  assert.ok(!titles('прага').includes('VUT'));
  // Without the taxonomy there are no cities, and nothing breaks.
  assert.deepEqual(search(DIRECTORY, 'брно'), []);
});

test('a one-letter typo in a longer word is forgiven', () => {
  assert.deepEqual(titles('strahof'), ['Strahov']); // replaced
  assert.deepEqual(titles('srahov'), ['Strahov']); // dropped
  assert.deepEqual(titles('sttrahov'), ['Strahov']); // doubled
  assert.deepEqual(titles('srtahov'), ['Strahov']); // swapped
  assert.deepEqual(titles('masarek'), ['Masarykova univerzita']); // in a prefix
  assert.deepEqual(titles('хвезды'), ['Kolej Hvězda']);
  assert.deepEqual(titles('strx'), []); // four letters get no typo
  assert.deepEqual(titles('strxxov'), []); // two typos are a different word
  assert.deepEqual(titles('hvezf'), ['Kolej Hvězda']); // five letters get one
});

test('short words get no typos: three letters are a different name', () => {
  assert.deepEqual(titles('fet'), []);
  assert.deepEqual(titles('вшт'), []);
  assert.deepEqual(titles('muno'), []);
});

test('several words match in any order', () => {
  assert.deepEqual(titles('fit чвут'), ['ČVUT FIT']);
  assert.deepEqual(titles('ЧВУТ fit'), ['ČVUT FIT']);
  assert.deepEqual(titles('фел, čvut'), ['ČVUT FEL']);
  assert.deepEqual(titles('fit vse'), []);
});

test('a word that matches nothing finds nothing', () => {
  assert.deepEqual(titles('гарвард'), []);
});

test('the start of a name is enough', () => {
  assert.deepEqual(titles('фе'), ['ČVUT FEL']);
  assert.deepEqual(titles('stra'), ['Strahov']);
});

test('a query of punctuation alone finds nothing rather than everything', () => {
  for (const query of ['--', '??', '«»', 'ьь']) {
    assert.deepEqual(titles(query), [], query);
  }
});

test('й and ё keep their letters, and stress marks do not split a word', () => {
  assert.ok(matches(['Хостел «Мой»'], 'мой'));
  assert.ok(!matches(['Хостел «Мои»'], 'мой'));
  assert.ok(matches(['Ёлка'], 'елка'));
  assert.ok(matches(['Masarykova univerzita'], 'ма́сарик'));
});

test('typos are a fallback: an exact match hides the near ones', () => {
  const schools = ['Univerzita Karlova', 'Univerzita Hradec Králové'];
  // «karlov» is one swap from «kralov»: that is a typo only when nothing
  // is spelled the way it was typed.
  assert.deepEqual(
    find(schools, (name) => [name], 'карлов'),
    ['Univerzita Karlova'],
  );
  assert.deepEqual(
    find(schools, (name) => [name], 'kralov'),
    ['Univerzita Hradec Králové'],
  );
  assert.deepEqual(
    find(['Univerzita Hradec Králové'], (name) => [name], 'карлов'),
    ['Univerzita Hradec Králové'],
  );
});

test('w is not v: Czech has no w to mistype', () => {
  assert.ok(!matches(['VŠE'], 'wse', false));
});

test('matches folds the fields it is given the same way', () => {
  assert.ok(matches(['Univerzita Karlova', 'UK', 'uk'], 'карлова'));
  assert.ok(matches(['Fakulta informačních technologií', 'FIT', null], 'фит'));
  assert.ok(matches(['Vysoká škola ekonomická v Praze', 'VŠE'], 'вше'));
  assert.ok(!matches(['Vysoká škola chemicko-technologická', 'VŠCHT'], 'вше'));
  assert.ok(matches(['anything'], '  '));
});
