import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  idFromSlug,
  priceText,
  sanitizeTutor,
  sanitizeTutors,
  tutorPath,
  tutorSummary,
} from '../site/src/catalog/tutors.ts';

const card = (over: Record<string, unknown> = {}) => ({
  user_id: 123,
  slug: 'anna-k-123',
  name: 'Анна К.',
  initials: 'АК',
  tone: 2,
  headline: 'Матанализ для ČVUT',
  services: ['Репетиторство'],
  subjects: ['Математический анализ'],
  price_from: { amount: 450, currency: 'CZK', unit: 'hour' },
  langs: ['ru', 'cs'],
  work_format: 'online',
  city: 'Praha',
  rating: null,
  deals_count: 3,
  ...over,
});

test('a tutor is addressed by the slug the catalog gives', () => {
  assert.equal(tutorPath('ru', 'anna-k-123'), '/tutors/anna-k-123/');
  assert.equal(tutorPath('en', 'anna-k-123'), '/en/tutors/anna-k-123/');
});

test('the id is what a slug ends with, whatever the name part says', () => {
  assert.equal(idFromSlug('anna-k-123'), 123);
  assert.equal(idFromSlug('anna-kovaleva-123'), 123);
  assert.equal(idFromSlug('123'), 123);
  // In capitals it is still the address of somebody, and gets the 301 to theirs.
  assert.equal(idFromSlug('Anna-K-123'), 123);
});

test('a slug that ends with no plain id names nobody', () => {
  for (const slug of [
    'anna-k',
    'anna-k-0123',
    'anna-k-',
    '-123',
    'anna k-123',
    'a--b-1',
    '',
    undefined,
  ])
    assert.equal(idFromSlug(slug), null, String(slug));
  // Past what a number holds exactly: no lookup, rather than the wrong one.
  assert.equal(idFromSlug(`a-${'9'.repeat(16)}`), null);
});

test('the tutors are checked as they arrive, not trusted', () => {
  const rows = sanitizeTutors([
    card(),
    card({ user_id: 0 }),
    card({ user_id: 5, slug: 'evil/../5' }),
    card({ user_id: 6, slug: 'someone-else-7' }),
    card({ user_id: 8, slug: 'x-8', name: '  ' }),
    card({ user_id: 9, slug: 'x-9', tone: 17 }),
    'nonsense',
  ]);
  assert.deepEqual(
    rows.map((r) => [r.user_id, r.tone]),
    [
      [123, 2],
      [9, 0],
    ],
  );
  assert.throws(() => sanitizeTutors({ not: 'a list' }));
});

test('what the page prints is what the catalog sent, and only that', () => {
  const [row] = sanitizeTutors([
    card({
      telegram_url: 'https://t.me/anna',
      services: ['A', 7, 'B'],
      price_from: { amount: 'free' },
    }),
  ]);
  assert.ok(row);
  assert.equal('telegram_url' in row, false);
  assert.deepEqual(row.services, ['A', 'B']);
  assert.equal(row.price_from, null);
});

test("a tutor's page is checked the same way, and a wrong one is no page", () => {
  const page = sanitizeTutor({
    ...card(),
    about: 'Учу пятый год.',
    place_note: null,
    stats: [{ code: 'stat.deals', value: '3' }],
    offers: [
      {
        service_type_name: 'Репетиторство',
        subject: 'Математический анализ',
        institution: 'ČVUT',
        price: { amount: 450, currency: 'CZK', unit: 'hour' },
        langs: ['ru'],
        work_format: 'online',
        options: ['Разбор задач'],
        note: null,
        turnaround_days: null,
      },
    ],
  });
  assert.equal(page.about, 'Учу пятый год.');
  assert.equal(page.offers[0]?.subject, 'Математический анализ');
  assert.throws(() => sanitizeTutor(card({ slug: 'bad slug' })));
});

const plain = (text: string | null) => text?.replace(/\s/g, ' ') ?? null;

test('a price reads in the page language, per what it is for', () => {
  assert.equal(
    plain(priceText('ru', { amount: 450, currency: 'CZK', unit: 'hour' })),
    '450 Kč / час',
  );
  assert.equal(
    plain(priceText('en', { amount: 1200, currency: 'CZK', unit: 'work' })),
    '1,200 Kč / piece of work',
  );
  assert.equal(
    plain(priceText('cs', { amount: 1200, currency: 'CZK', unit: 'hour' })),
    '1 200 Kč / hodina',
  );
  assert.equal(priceText('cs', null), null);
});

test('a page summary is the tutor’s own words, once, and never empty', () => {
  const base = {
    name: 'Анна К.',
    headline: null,
    about: null,
    subjects: [],
    services: [],
  };
  assert.equal(tutorSummary({ ...base, about: 'Учу пятый год.' }), 'Учу пятый год');
  assert.equal(
    tutorSummary({ ...base, subjects: ['Матанализ', 'Физика'] }),
    'Матанализ, Физика',
  );
  // Nostrification has no subject: the service names it.
  assert.equal(tutorSummary({ ...base, services: ['Нострификация'] }), 'Нострификация');
  assert.equal(tutorSummary(base), null);
  assert.equal(tutorSummary({ ...base, about: 'x'.repeat(300) })?.length, 140);
});

// ── reading the catalog ──────────────────────────────────────────────────

const requested: string[] = [];
const answers = new Map<string, () => Response>();
process.env.CATALOG_API_URL = 'http://catalog.test';
process.env.WEBAPI_URL = 'http://webapi.test';
globalThis.fetch = (async (input: string | URL | Request) => {
  const url = String(input);
  requested.push(url);
  const answer = [...answers].find(([prefix]) => url.startsWith(prefix))?.[1];
  return answer ? answer() : new Response('nope', { status: 500 });
}) as typeof fetch;
const json =
  (body: unknown, status = 200) =>
  () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });

const { tutor } = await import('../site/src/catalog/source.ts');
const { tutorPage } = await import('../site/src/catalog/load.ts');
const { catalogSitemap: sitemapOf } = await import('../site/src/catalog/sitemap.ts');
// No texts: the content layer is Astro's, and the test is about the tutors.
const catalogSitemap = sitemapOf(async () => []);

test('an id that is not on the list is no page, and never a request to the catalog', async () => {
  answers.set('http://catalog.test/api/v1/public/helpers?lang=uk', json([card()]));
  requested.length = 0;
  assert.equal(await tutor('uk', 999), null);
  assert.deepEqual(
    requested.filter((url) => url.includes('/helpers/')),
    [],
  );
});

test('a tutor the catalog no longer shows is gone, not kept from before', async () => {
  answers.set('http://catalog.test/api/v1/public/helpers?lang=cs', json([card()]));
  answers.set(
    'http://catalog.test/api/v1/public/helpers/123?lang=cs',
    json({ detail: 'no' }, 404),
  );
  assert.equal(await tutor('cs', 123), null);
});

test('a stale or uppercased slug is sent to the catalog’s own, for good', async () => {
  answers.set('http://catalog.test/api/v1/public/helpers?lang=en', json([card()]));
  answers.set(
    'http://catalog.test/api/v1/public/helpers/123?lang=en',
    json({ ...card(), about: null, offers: [] }),
  );
  for (const slug of ['anna-123', 'ANNA-K-123']) {
    const answer = await tutorPage('en', slug);
    assert.ok(answer instanceof Response, slug);
    assert.equal(answer.status, 301);
    assert.equal(answer.headers.get('Location'), '/en/tutors/anna-k-123/');
  }
  assert.ok(!((await tutorPage('en', 'anna-k-123')) instanceof Response));
});

test('the catalog sitemap lists the universities when the tutors cannot be read', async () => {
  answers.set('http://webapi.test/api/public/catalog', json([]));
  answers.set('http://catalog.test/api/v1/universities', json([]));
  answers.delete('http://catalog.test/api/v1/public/helpers?lang=ru');
  // biome-ignore lint/suspicious/noExplicitAny: only `site` is read.
  const response = await catalogSitemap({ site: new URL('https://konnekt.cz/') } as any);
  assert.equal(response.status, 200);
  const xml = await response.text();
  assert.match(xml, /konnekt\.cz\/universities\//);
  assert.doesNotMatch(xml, /tutors/);
});

test('the catalog sitemap lists a university and its faculties in the languages they have our text in', async () => {
  answers.set('http://webapi.test/api/public/catalog', json([]));
  answers.set('http://catalog.test/api/v1/universities', json([]));
  const place = (lang: 'ru' | 'uk', university: string, faculty: string | null) => ({
    place: {
      lang,
      university,
      faculty,
      address: faculty ? `${university}/${faculty}` : university,
    },
  });
  const withTexts = sitemapOf(async () => [
    place('ru', 'cvut', null),
    place('ru', 'cvut', 'fit'),
    place('uk', 'cvut', 'fit'),
  ]);
  // biome-ignore lint/suspicious/noExplicitAny: only `site` is read.
  const xml = await (
    await withTexts({ site: new URL('https://konnekt.cz/') } as any)
  ).text();
  assert.match(xml, /<loc>https:\/\/konnekt\.cz\/universities\/cvut\/<\/loc>/);
  // No chats and no Ukrainian text: the Ukrainian page of the university is not listed.
  assert.doesNotMatch(xml, /<loc>https:\/\/konnekt\.cz\/uk\/universities\/cvut\/<\/loc>/);
  assert.match(xml, /<loc>https:\/\/konnekt\.cz\/uk\/universities\/cvut\/fit\/<\/loc>/);
  assert.doesNotMatch(xml, /\/en\/universities\/cvut\/fit\//);
});
