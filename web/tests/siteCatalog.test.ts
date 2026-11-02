import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  anchors,
  type CatalogUniversity,
  catalogue,
  cityFromSlug,
  citySlug,
  indexable,
  jsonLd,
  mainChat,
  sections,
  universitiesWithChats,
} from '../site/src/catalog/catalog.ts';
import { langOf } from '../site/src/catalog/page.ts';
import { remembered } from '../site/src/catalog/remembered.ts';
import { sanitizeUniversities } from '../site/src/catalog/source.ts';
import type { PublicChat } from '../src/lib/chats.ts';

const chat = (title: string, over: Partial<PublicChat> = {}): PublicChat => ({
  title,
  link: `https://t.me/${title.replace(/\W+/g, '_').toLowerCase()}_chat`,
  group: null,
  institution: null,
  activity: 'unknown',
  member_count: null,
  is_forum: false,
  kind: 'group',
  external: false,
  avatar: null,
  city: null,
  topic: null,
  ...over,
});

const university = (code: string, short: string, city: string): CatalogUniversity => ({
  code,
  name: `${short} university`,
  short_name: short,
  city,
  site_url: `https://www.${code}.cz`,
});

const CVUT = university('cvut', 'ČVUT', 'Praha');
const VSE = university('vse', 'VŠE', 'Praha');
const MUNI = university('muni', 'MUNI', 'Brno');

// In the order supervisor sends them: a group's own chat first, then the larger.
const cvut = chat('ČVUT | ЧВУТ', {
  group: 'ČVUT | ЧВУТ',
  institution: 'cvut',
  city: 'Praha',
  topic: 'university',
  member_count: 1500,
});
const strahov = chat('Strahov', {
  group: 'ČVUT | ЧВУТ',
  institution: 'cvut',
  city: 'Praha',
  topic: 'dorms',
  member_count: 1900,
});
const fit = chat('ČVUT FIT', {
  group: 'ČVUT | ЧВУТ',
  institution: 'cvut',
  city: 'Praha',
  topic: 'university',
  member_count: 900,
});
const volleyball = chat('Волейбол', {
  institution: 'cvut',
  city: 'Praha',
  topic: 'dorms',
  external: true,
});
const vse = chat('VŠE', {
  group: 'VŠE',
  institution: 'vse',
  city: 'Praha',
  topic: 'university',
});
const upce = chat('UPCE', { group: 'UPCE', city: 'Pardubice', topic: 'university' });
const upceFes = chat('UPCE FES', {
  group: 'UPCE',
  city: 'Pardubice',
  topic: 'university',
});
const zcu = chat('ZČU | ЗЧУ', { city: 'Plzeň', topic: 'university', external: true });
const maths = chat('Matematika v ČR', { topic: 'subjects' });
const ntk = chat('NTK', { city: 'Praha', topic: 'general' });
const it = chat('IT Чехия', { topic: 'work_it' });

const ALL = [cvut, strahov, fit, vse, upce, upceFes, zcu, maths, ntk, it, volleyball];

test('a university is listed by its code with every chat that names it', () => {
  const listed = universitiesWithChats([VSE, MUNI, CVUT], ALL);

  // The catalogue's order, which is supervisor's: ours, then the larger.
  assert.deepEqual(
    listed.map(({ university: u }) => u.code),
    ['cvut', 'vse'],
  );
  // A chat outside the university's group still names it: it is on its page.
  assert.deepEqual(listed[0]?.chats, [cvut, strahov, fit, volleyball]);
});

test('a university with no chat has no page', () => {
  const listed = universitiesWithChats([MUNI], ALL);

  assert.deepEqual(listed, []);
});

test('a university page goes to search from two chats', () => {
  const [withCvut, withVse] = universitiesWithChats([CVUT, VSE], ALL);

  assert.equal(withCvut && indexable(withCvut), true);
  assert.equal(withVse && indexable(withVse), false);
});

test('the main chat is the university’s own, not its largest', () => {
  // Strahov, a dorm, is the largest: Azamat's reason for the main chat (agora 10228).
  assert.equal(mainChat([cvut, strahov, fit, volleyball]), cvut);
});

test('without a chat of its own, the main chat is the largest common one', () => {
  const lone = [
    strahov,
    fit,
    chat('ČVUT FEL', { ...fit, title: 'ČVUT FEL', member_count: 1200 }),
  ];

  assert.equal(mainChat(lone)?.title, 'ČVUT FEL');
});

test('a channel is never the main chat, and a lone chat needs no mark', () => {
  const news = chat('ČVUT новости', {
    group: 'ČVUT новости',
    topic: 'university',
    kind: 'channel',
    external: true,
    member_count: 5000,
  });

  assert.equal(mainChat([news, fit]), fit);
  assert.equal(mainChat([vse]), null);
});

test('a university page reads by heading, its main chat first', () => {
  const page = sections([fit, strahov, cvut, volleyball]);

  assert.deepEqual(
    page.map(({ topic, chats }) => [topic, chats.map((c) => c.title)]),
    [
      ['university', ['ČVUT | ЧВУТ', 'ČVUT FIT']],
      ['dorms', ['Strahov', 'Волейбол']],
    ],
  );
});

test('the public catalogue: one line a university, the rest under their headings', () => {
  const { universities, loose, topics } = catalogue(ALL, [CVUT, VSE]);

  assert.deepEqual(
    universities.map((u) => [u.code, u.name, u.main?.title ?? null, u.chats.length]),
    [
      ['cvut', 'ČVUT', 'ČVUT | ЧВУТ', 4],
      ['vse', 'VŠE', null, 1],
      // No page in the catalog: every chat of it is here.
      [null, 'UPCE', 'UPCE', 2],
    ],
  );
  assert.deepEqual(
    loose.map((c) => c.title),
    ['ZČU | ЗЧУ'],
  );
  assert.deepEqual(
    topics.map(({ topic, chats }) => [topic, chats.map((c) => c.title)]),
    [
      ['subjects', ['Matematika v ČR']],
      ['work_it', ['IT Чехия']],
      ['general', ['NTK']],
    ],
  );
});

test('a city keeps its own and those for all of Czechia', () => {
  const { universities, loose, topics } = catalogue(ALL, [CVUT, VSE], 'Pardubice');

  assert.deepEqual(
    universities.map((u) => u.name),
    ['UPCE'],
  );
  assert.deepEqual(loose, []);
  assert.deepEqual(
    topics.map(({ chats }) => chats.map((c) => c.title)),
    [['Matematika v ČR'], ['IT Чехия']],
  );
});

test('a city is addressed without diacritics or spaces', () => {
  assert.equal(citySlug('České Budějovice'), 'ceske-budejovice');
  assert.equal(citySlug('Praha'), 'praha');
  const choices = ['Praha', 'České Budějovice'];
  assert.equal(cityFromSlug('ceske-budejovice', choices), 'České Budějovice');
  assert.equal(cityFromSlug('Praha', choices), null);
  assert.equal(cityFromSlug('narnia', choices), null);
  assert.equal(cityFromSlug(null, choices), null);
});

test('a chat’s anchor is its public name, and never twice the same', () => {
  const named = chat('ČVUT FIT', { link: 'https://t.me/CVUT_FIT' });
  const invite = chat('Kolej Podolí', { link: 'https://t.me/+AbCdEf123' });
  const twin = chat('Kolej Podolí', { link: 'https://t.me/+ZyXwVu987' });

  const ids = anchors([named, invite, twin]);

  assert.deepEqual([...ids.values()], ['cvut_fit', 'kolej-podoli', 'kolej-podoli-2']);
});

test('an answer is kept for a while, and outlives a failing source', async () => {
  let now = 0;
  let calls = 0;
  let failing = false;
  const read = remembered(
    async () => {
      calls++;
      if (failing) throw new Error('down');
      return calls;
    },
    { ttl: 60_000, now: () => now },
  );

  assert.equal(await read(), 1);
  now = 30_000;
  assert.equal(await read(), 1);
  now = 61_000;
  assert.equal(await read(), 2);
  failing = true;
  now = 200_000;
  // Stale rather than an error page: the API being down is not the catalogue being empty.
  assert.equal(await read(), 2);
});

test('with nothing to fall back on, a failure is the caller’s', async () => {
  const read = remembered(
    async () => {
      throw new Error('down');
    },
    { ttl: 60_000, now: () => 0 },
  );

  await assert.rejects(read(), /down/);
});

test('the universities are checked as they arrive, not trusted', () => {
  const rows = sanitizeUniversities([
    {
      code: 'cvut',
      name: 'ČVUT',
      short_name: 'ČVUT',
      city: 'Praha',
      site_url: 'https://www.cvut.cz',
    },
    {
      code: 'vse',
      name: 'VŠE',
      short_name: null,
      city: null,
      site_url: 'javascript:alert(1)',
    },
    { code: 'Bad Code', name: 'x' },
    { code: 'uk', name: '' },
    null,
  ]);

  assert.deepEqual(rows, [
    {
      code: 'cvut',
      name: 'ČVUT',
      short_name: 'ČVUT',
      city: 'Praha',
      site_url: 'https://www.cvut.cz',
    },
    // A link the page prints: https only.
    { code: 'vse', name: 'VŠE', short_name: null, city: null, site_url: null },
  ]);
  assert.throws(() => sanitizeUniversities({ detail: 'down' }));
});

test('a chat’s title cannot close the page’s JSON-LD script', () => {
  // The admins of a listed group choose its title.
  const text = jsonLd({ name: 'Dorm</script><script>window.PWNED=1</script>' });

  assert.equal(text.includes('<'), false);
  assert.deepEqual(JSON.parse(text), {
    name: 'Dorm</script><script>window.PWNED=1</script>',
  });
});

test('a catalog page’s language is its prefix, and Russian has none', () => {
  assert.equal(langOf(undefined), 'ru');
  assert.equal(langOf('uk'), 'uk');
  assert.equal(langOf('en'), 'en');
  // One address per page: Russian is at the root, never under /ru/.
  assert.equal(langOf('ru'), null);
  assert.equal(langOf('xx'), null);
});
