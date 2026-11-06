import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  idFromSlug,
  priceText,
  sanitizeTutor,
  sanitizeTutors,
  tutorPath,
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
});

test('a slug that ends with no plain id names nobody', () => {
  for (const slug of [
    'anna-k',
    'anna-k-0123',
    'anna-k-',
    '-123',
    'Anna-123',
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
