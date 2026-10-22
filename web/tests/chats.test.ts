import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  blocks,
  byOwner,
  chipFor,
  cityChoices,
  defaultCity,
  directory,
  type Entry,
  initials,
  ownUniversity,
  type PublicChat,
  placeOf,
  rowDotFor,
  sanitize,
  search,
  sectionAvatar,
  sectionHint,
  sectionMembers,
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
    external: false,
    avatar: null,
    city: null,
    topic: null,
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

test('a row marks how a chat talks only when it talks more than most', () => {
  assert.equal(rowDotFor('busy'), 'busy');
  assert.equal(rowDotFor('active'), 'active');
  assert.equal(rowDotFor('quiet'), null);
  assert.equal(rowDotFor('unknown'), null);
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
  assert.deepEqual(today?.kind === 'section' && sectionHint(today), {
    count: 4,
    names: 'ČVUT FA, ČVUT FIT, ČVUT FEL…',
    more: false,
  });
  const [tomorrow] = directory(SAMPLE).entries;
  assert.deepEqual(tomorrow?.kind === 'section' && sectionHint(tomorrow), {
    count: 2,
    names: 'ČVUT FIT, ČVUT FEL',
    more: true,
  });
  const three = directory([...TODAY.slice(0, 3), chat(CVUT, CVUT)]).entries[0];
  assert.deepEqual(three?.kind === 'section' && sectionHint(three), {
    count: 3,
    names: 'ČVUT FA, ČVUT FIT, ČVUT FEL',
    more: true,
  });
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

test("a chat is somebody else's only when supervisor says so", () => {
  const external = sanitize(
    [true, false, 'true', undefined].map((value, n) => ({
      title: `Chat ${n}`,
      link: `https://t.me/chat_${n}`,
      group: null,
      activity: 'quiet',
      external: value,
    })),
  ).map((c) => c.external);
  assert.deepEqual(external, [true, false, false, false]);
});

test("a section's own chats come apart from the ones it only lists", () => {
  const { ours, others } = byOwner([
    chat('ČVUT | ЧВУТ', CVUT),
    chat('ČVUT FJFI', CVUT, { external: true }),
    chat('ČVUT FIT', CVUT),
    chat('PODOLI', CVUT, { external: true }),
  ]);
  assert.deepEqual(
    ours.map((c) => c.title),
    ['ČVUT | ЧВУТ', 'ČVUT FIT'],
  );
  assert.deepEqual(
    others.map((c) => c.title),
    ['ČVUT FJFI', 'PODOLI'],
  );
});

test("a chat's place is its university, or its topic, and its city", () => {
  const taxonomy = [
    {
      code: 'cvut',
      name: 'České vysoké učení technické v Praze',
      short_name: 'ČVUT',
      city: 'Praha',
    },
    { code: 'vut', name: 'Vysoké učení technické v Brně', short_name: null, city: null },
  ];
  const university = { topic: 'university' } as const;
  assert.deepEqual(
    placeOf(chat('ČVUT FIT', CVUT, { ...university, institution: 'cvut' }), taxonomy),
    { university: 'České vysoké učení technické v Praze', city: 'Praha' },
  );
  // The chat's own city stands; the taxonomy's only fills a gap.
  assert.deepEqual(
    placeOf(
      chat('VUT FEKT', 'VUT', { ...university, institution: 'vut', city: 'Brno' }),
      taxonomy,
    ),
    { university: 'Vysoké učení technické v Brně', city: 'Brno' },
  );
  // Not yet in the taxonomy: no name rather than a code.
  assert.deepEqual(
    placeOf(chat('MUNI', 'MUNI', { ...university, institution: 'muni' }), taxonomy),
    { university: null, city: null },
  );
  // A dormitory is a dormitory, whichever university its residents attend.
  assert.deepEqual(
    placeOf(
      chat('Strahov', null, { topic: 'dorms', institution: 'cvut', city: 'Praha' }),
      taxonomy,
    ),
    { university: null, city: 'Praha' },
  );
});

test("a chat's photo is the address supervisor gave, and only an address of ours", () => {
  const base = { title: 'ČVUT FIT', link: 'https://t.me/cvut_fit', group: null };
  const [own, absolute, traversal, missing, wrongType] = sanitize([
    { ...base, avatar: '/api/public/avatars/AQAD-x_1' },
    // A page must not be handed somebody else's image host, whatever the server says.
    { ...base, avatar: 'https://example.com/a.jpg' },
    { ...base, avatar: '/api/public/avatars/../../console' },
    base,
    { ...base, avatar: 42 },
  ]);
  assert.equal(own?.avatar, '/api/public/avatars/AQAD-x_1');
  assert.equal(absolute?.avatar, null);
  assert.equal(traversal?.avatar, null);
  assert.equal(missing?.avatar, null);
  assert.equal(wrongType?.avatar, null);
});

test('a section shows the photo of its own chat, and none when that has no photo', () => {
  const section = (chats: PublicChat[]) =>
    ({ kind: 'section', name: CVUT, chats }) as Extract<Entry, { kind: 'section' }>;
  const own = chat(CVUT, CVUT, { avatar: '/api/public/avatars/own' });
  const fit = chat('ČVUT FIT', CVUT, { avatar: '/api/public/avatars/fit' });
  assert.equal(sectionAvatar(section([fit, own])), '/api/public/avatars/own');
  // A faculty's photo says nothing about the university: the letters stay.
  assert.equal(sectionAvatar(section([fit, chat(CVUT, CVUT)])), null);
  assert.equal(sectionAvatar(section([fit])), null);
});

test('a section counts the people of its own chat, and none when that was never measured', () => {
  const section = (chats: PublicChat[]) =>
    ({ kind: 'section', name: CVUT, chats }) as Extract<Entry, { kind: 'section' }>;
  const fit = chat('ČVUT FIT', CVUT, { member_count: 983 });
  assert.equal(
    sectionMembers(section([fit, chat(CVUT, CVUT, { member_count: 1513 })])),
    1513,
  );
  // A faculty's count is not the university's.
  assert.equal(sectionMembers(section([fit, chat(CVUT, CVUT)])), null);
  assert.equal(sectionMembers(section([fit])), null);
});

// ── variant B: cities and topics ─────────────────────────────────────────

const PRAGUE_AND_BRNO: PublicChat[] = [
  chat('ČVUT | ЧВУТ', CVUT, { city: 'Praha', topic: 'university', institution: 'cvut' }),
  chat('ČVUT FIT', CVUT, { city: 'Praha', topic: 'university', institution: 'cvut' }),
  chat('VUT', 'VUT', { city: 'Brno', topic: 'university', institution: 'vut' }),
  chat('VUT FIT', 'VUT', { city: 'Brno', topic: 'university', institution: 'vut' }),
  chat('VŠB-TUO', null, { city: 'Ostrava', topic: 'university' }),
  chat('Fyzika v ČR', null, { topic: 'subjects' }),
  chat('Strahov', null, { city: 'Praha', topic: 'dorms', institution: 'cvut' }),
  chat('IT Чехия', null, { topic: 'work_it' }),
  chat('NTK', null, { city: 'Praha', topic: 'general' }),
  chat('Flood', null),
];

function headings(city: string | null) {
  return blocks(PRAGUE_AND_BRNO, { mine: null, city }).map((block) => [
    block.heading,
    block.entries.map((entry) =>
      entry.kind === 'section' ? entry.name : entry.chat.title,
    ),
  ]);
}

test('universities come first, then subjects, dorms, work and IT, and the rest', () => {
  assert.deepEqual(headings(null), [
    ['university', [CVUT, 'VUT', 'VŠB-TUO']],
    ['subjects', ['Fyzika v ČR']],
    ['dorms', ['Strahov']],
    ['work_it', ['IT Чехия']],
    ['general', ['NTK', 'Flood']],
  ]);
});

test('a city keeps its own chats and those for all of Czechia', () => {
  assert.deepEqual(headings('Praha'), [
    ['university', [CVUT]],
    ['subjects', ['Fyzika v ČR']],
    ['dorms', ['Strahov']],
    ['work_it', ['IT Чехия']],
    ['general', ['NTK', 'Flood']],
  ]);
  assert.deepEqual(headings('Brno'), [
    ['university', ['VUT']],
    ['subjects', ['Fyzika v ČR']],
    ['work_it', ['IT Чехия']],
    ['general', ['Flood']],
  ]);
});

test("within a block a student's own university still comes first", () => {
  const [universities] = blocks(PRAGUE_AND_BRNO, { mine: 'vut', city: null });
  assert.equal(
    universities?.entries[0]?.kind === 'section' && universities.entries[0].name,
    'VUT',
  );
});

test('the city chips are the cities that have chats, the busiest first', () => {
  assert.deepEqual(cityChoices(PRAGUE_AND_BRNO), ['Praha', 'Brno', 'Ostrava']);
});

test("the city starts at the student's university's, or at all of them", () => {
  const choices = ['Praha', 'Brno', 'Ostrava'];
  assert.equal(defaultCity(choices, 'Brno'), 'Brno');
  // A university in a city with no chats of its own would show a near-empty list.
  assert.equal(defaultCity(choices, 'Olomouc'), null);
  assert.equal(defaultCity(choices, undefined), null);
});

test('a city and a topic are checked at the boundary too', () => {
  const [kept, odd] = sanitize([
    { title: 'Strahov', link: 'https://t.me/strahov', city: 'Praha', topic: 'dorms' },
    { title: 'Odd', link: 'https://t.me/odd', city: 7, topic: 'sport' },
  ]);
  assert.deepEqual([kept?.city, kept?.topic], ['Praha', 'dorms']);
  assert.deepEqual([odd?.city, odd?.topic], [null, null]);
});
