import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  chipFor,
  directory,
  initials,
  ownUniversity,
  type PublicChat,
  placeOf,
  sanitize,
  search,
  sectionHint,
} from '../src/lib/chats.ts';

function chat(
  title: string,
  group: string | null,
  over: Partial<PublicChat> = {},
): PublicChat {
  return {
    title,
    link: `https://t.me/${title.replace(/\W+/g, '_').toLowerCase()}`,
    group,
    institution: null,
    activity: 'active',
    member_count: null,
    is_forum: false,
    ...over,
  };
}

const CVUT = 'ČVUT | ЧВУТ';

// The shape supervisor serves once a university's own chat heads its section
// (supervisor #122): one university with its faculties, one with a single
// chat, and chats that belong to nothing.
const SAMPLE: PublicChat[] = [
  chat('ČVUT | ЧВУТ', CVUT),
  chat('ČVUT FIT', CVUT),
  chat('ČVUT FEL', CVUT),
  chat('Masarykova univerzita', 'Masarykova univerzita'),
  chat('Strahov', null),
  chat('IT Чехия', null),
];

/** What the directory draws, reduced to titles. */
function shape(chats: PublicChat[]) {
  return directory(chats).entries.map((entry) =>
    entry.kind === 'section'
      ? { section: entry.name, chats: entry.chats.map((c) => c.title) }
      : { chat: entry.chat.title },
  );
}

test('chats that share a group form a section, in the order given', () => {
  assert.deepEqual(shape(SAMPLE)[0], {
    section: CVUT,
    chats: ['ČVUT | ЧВУТ', 'ČVUT FIT', 'ČVUT FEL'],
  });
});

test('a group with one chat is that chat, not a section', () => {
  assert.deepEqual(shape(SAMPLE), [
    { section: CVUT, chats: ['ČVUT | ЧВУТ', 'ČVUT FIT', 'ČVUT FEL'] },
    { chat: 'Masarykova univerzita' },
  ]);
});

test('chats without a group come apart, last, in the order given', () => {
  const { rest } = directory(SAMPLE);
  assert.deepEqual(
    rest.map((c) => c.title),
    ['Strahov', 'IT Чехия'],
  );
});

test('a group split by the server stays one section', () => {
  const split = [chat('ČVUT FIT', CVUT), chat('Strahov', null), chat('ČVUT FEL', CVUT)];
  assert.deepEqual(shape(split), [{ section: CVUT, chats: ['ČVUT FIT', 'ČVUT FEL'] }]);
});

test('search ignores case and diacritics', () => {
  assert.deepEqual(
    search(SAMPLE, 'cvut fit').map((c) => c.title),
    ['ČVUT FIT'],
  );
  assert.deepEqual(
    search(SAMPLE, 'strahov').map((c) => c.title),
    ['Strahov'],
  );
});

test('search matches the group too, so a university finds its faculties', () => {
  assert.equal(search(SAMPLE, 'ЧВУТ').length, 3);
});

test('every word has to match, in any order', () => {
  assert.deepEqual(
    search(SAMPLE, 'fel čvut').map((c) => c.title),
    ['ČVUT FEL'],
  );
});

test('an empty query finds nothing to narrow, so it returns everything', () => {
  assert.equal(search(SAMPLE, '   ').length, SAMPLE.length);
});

test('activity is a chip only when supervisor measured it', () => {
  assert.equal(chipFor('busy'), 'busy');
  assert.equal(chipFor('active'), 'active');
  assert.equal(chipFor('quiet'), 'quiet');
  assert.equal(chipFor('unknown'), null);
});

test('a tile takes its letters from the first of two names', async () => {
  assert.equal(initials('ČVUT | ЧВУТ'), 'ČVUT');
  assert.equal(initials('Fyzika v ČR'), 'FV');
  assert.equal(initials('Strahov'), 'ST');
});

test('a faculty shows its own abbreviation, not its university one', async () => {
  assert.equal(initials('ČVUT FIT'), 'FIT');
  assert.equal(initials('ČVUT FSv'), 'FSV');
  assert.equal(initials('Kolej Hvězda'), 'KH');
  assert.equal(initials('IT Чехия | Опыт, работа, новости'), 'IЧ');
});

// The shape production serves today: the university's own chat has no group
// and its faculties do.
const TODAY: PublicChat[] = [
  chat('ČVUT FA', CVUT),
  chat('ČVUT FIT', CVUT),
  chat('ČVUT FEL', CVUT),
  chat('ČVUT FS', CVUT),
  chat('ČVUT | ЧВУТ', null),
];

test('a section hint names its chats, skipping only the one named like it', () => {
  const [today] = directory(TODAY).entries;
  assert.equal(
    today?.kind === 'section' && sectionHint(today),
    'ČVUT FA, ČVUT FIT, ČVUT FEL',
  );
  const [tomorrow] = directory(SAMPLE).entries;
  assert.equal(
    tomorrow?.kind === 'section' && sectionHint(tomorrow),
    'ČVUT FIT, ČVUT FEL',
  );
});

test('a one-word abbreviation stays whole, so VŠE and VŠCHT differ', () => {
  assert.equal(initials('VŠE'), 'VŠE');
  assert.equal(initials('VŠCHT'), 'VŠCHT');
  assert.equal(initials('VUT'), 'VUT');
  assert.equal(initials('Masarykova univerzita'), 'MU');
});

test('what arrives from the other backend is checked, not trusted', () => {
  const clean = sanitize([
    { title: 'ČVUT FIT', link: 'https://t.me/cvut_fit', group: CVUT, activity: 'busy' },
    { title: 'Invite', link: 'https://t.me/+AbCdEf', group: null, activity: 'loud' },
    { title: 'Elsewhere', link: 'https://example.com/x', group: null, activity: 'busy' },
    { link: 'https://t.me/no_title', group: null, activity: 'busy' },
    'not a chat',
  ]);
  assert.deepEqual(
    clean.map((c) => [c.title, c.activity]),
    [
      ['ČVUT FIT', 'busy'],
      ['Invite', 'unknown'],
    ],
  );
});

test("a student's own university comes first, the rest keep their order", () => {
  const chats = [
    chat('VŠE FIS', 'VŠE', { institution: 'vse' }),
    chat('VŠE FFÚ', 'VŠE', { institution: 'vse' }),
    chat('ČVUT FIT', CVUT, { institution: 'cvut' }),
    chat('ČVUT FEL', CVUT, { institution: 'cvut' }),
    chat('UK Hostel', 'UK', { institution: 'uk' }),
  ];
  const names = (mine: string | null) =>
    directory(chats, mine).entries.map((entry) =>
      entry.kind === 'section' ? entry.name : entry.chat.title,
    );
  assert.deepEqual(names('cvut'), [CVUT, 'VŠE', 'UK Hostel']);
  assert.deepEqual(names(null), ['VŠE', CVUT, 'UK Hostel']);
  assert.deepEqual(names('muni'), ['VŠE', CVUT, 'UK Hostel']);
  assert.deepEqual(names('uk'), ['UK Hostel', 'VŠE', CVUT]);
});

test('a faculty belongs to its university, found through the taxonomy', () => {
  const taxonomy = [
    {
      id: 1,
      code: 'cvut',
      parent_id: null,
      faculties: [{ id: 11, code: 'cvut-fit', parent_id: 1, faculties: [] }],
    },
    { id: 2, code: 'vse', parent_id: null, faculties: [] },
  ];
  assert.equal(
    ownUniversity({ id: 11, code: 'cvut-fit', parent_id: 1 }, taxonomy),
    'cvut',
  );
  assert.equal(ownUniversity({ id: 2, code: 'vse', parent_id: null }, taxonomy), 'vse');
  assert.equal(ownUniversity(null, taxonomy), null);
  // A faculty whose university is not in the list yet: its own code is no match.
  assert.equal(ownUniversity({ id: 99, code: 'x-y', parent_id: 98 }, taxonomy), null);
});

test('an institution code that is not a code is dropped at the boundary', () => {
  const [kept, dropped] = sanitize([
    {
      title: 'A',
      link: 'https://t.me/a',
      group: null,
      institution: 'cvut',
      activity: 'busy',
    },
    {
      title: 'B',
      link: 'https://t.me/b',
      group: null,
      institution: '<b>x</b>',
      activity: 'busy',
    },
  ]);
  assert.equal(kept?.institution, 'cvut');
  assert.equal(dropped?.institution, null);
});

test('a member count is a whole number of people or nothing at all', () => {
  const counts = sanitize(
    [1248, 0, null, -3, 2.5, '1248', undefined].map((member_count, n) => ({
      title: `Chat ${n}`,
      link: `https://t.me/chat_${n}`,
      group: null,
      activity: 'busy',
      member_count,
    })),
  ).map((c) => c.member_count);
  // Zero is a measured empty room; anything that is not a count is "not measured".
  assert.deepEqual(counts, [1248, 0, null, null, null, null, null]);
});

test('a chat has topics only when supervisor says so', () => {
  const forums = sanitize(
    [true, false, 'true', undefined].map((is_forum, n) => ({
      title: `Chat ${n}`,
      link: `https://t.me/chat_${n}`,
      group: null,
      activity: 'busy',
      is_forum,
    })),
  ).map((c) => c.is_forum);
  assert.deepEqual(forums, [true, false, false, false]);
});

test("a chat's place is its university and that university's city", () => {
  const taxonomy = [
    {
      code: 'cvut',
      name: 'České vysoké učení technické v Praze',
      short_name: 'ČVUT',
      city: 'Praha',
    },
    { code: 'vut', name: 'Vysoké učení technické v Brně', short_name: null, city: null },
  ];
  assert.equal(
    placeOf(chat('ČVUT FIT', CVUT, { institution: 'cvut' }), taxonomy),
    'České vysoké učení technické v Praze · Praha',
  );
  assert.equal(
    placeOf(chat('VUT FEKT', 'VUT', { institution: 'vut' }), taxonomy),
    'Vysoké učení technické v Brně',
  );
  // Not yet in the taxonomy, or no university at all: nothing rather than a code.
  assert.equal(placeOf(chat('MUNI', 'MUNI', { institution: 'muni' }), taxonomy), null);
  assert.equal(placeOf(chat('Strahov', null), taxonomy), null);
});
