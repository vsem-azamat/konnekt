/*
 * What «Документы и жизнь» draws given the paid places: a card where one is
 * live, an invitation where a place is free and somebody answers, the plain
 * row otherwise, and today's tiles when there is nothing paid to show.
 */

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { handleOf, priceFrom, shelf } from '../src/lib/showcase.ts';
import type { HomeSection, ShowcaseCard, ShowcaseSlot } from '../src/lib/types.ts';

function section(code: string): HomeSection {
  return {
    kind: 'service_type',
    code,
    group: 'life',
    name: code,
    hint: null,
    tone: 1,
    count: 0,
    avatars: [],
  };
}

const LIFE = ['insurance', 'bank_letter', 'translation', 'residence', 'housing'].map(
  section,
);

function card(id: number, service: string): ShowcaseCard {
  return {
    id,
    service,
    partner: 'Lumen',
    title: 'Выписка',
    line: null,
    text: null,
    price_from: null,
    photo: null,
    until: null,
    write_to: 'https://t.me/lumen',
  };
}

function slots(taken: Record<string, number> = {}): ShowcaseSlot[] {
  return ['bank_letter', 'insurance', 'residence'].map((service) => ({
    service,
    card: service in taken ? card(taken[service] as number, service) : null,
  }));
}

const CONTACT = 'https://t.me/konnekt_ads';

test('nothing paid and nobody to write to leaves the tiles as they are', () => {
  assert.equal(shelf(slots(), LIFE, null), null);
});

test('with somebody to write to, every free place invites, in the places order', () => {
  const drawn = shelf(slots(), LIFE, CONTACT);
  assert.ok(drawn);
  assert.deepEqual(
    drawn.places.map((place) => [place.kind, place.section?.code]),
    [
      ['open', 'bank_letter'],
      ['open', 'insurance'],
      ['open', 'residence'],
    ],
  );
  assert.deepEqual(
    drawn.rows.map((row) => row.code),
    ['translation', 'housing'],
  );
});

test('a live card takes its place, the others still invite', () => {
  const drawn = shelf(slots({ insurance: 7 }), LIFE, CONTACT);
  assert.ok(drawn);
  assert.deepEqual(
    drawn.places.map((place) => place.kind),
    ['open', 'card', 'open'],
  );
});

test('without a contact a free place is its plain row, not a dead-end invitation', () => {
  const drawn = shelf(slots({ insurance: 7 }), LIFE, '');
  assert.ok(drawn);
  assert.deepEqual(
    drawn.places.map((place) => place.kind),
    ['card'],
  );
  assert.deepEqual(
    drawn.rows.map((row) => row.code),
    ['bank_letter', 'translation', 'residence', 'housing'],
  );
});

test('a place for a service the shelf does not list is not invited to', () => {
  const drawn = shelf(
    slots(),
    LIFE.filter((one) => one.code !== 'residence'),
    CONTACT,
  );
  assert.ok(drawn);
  assert.equal(drawn.places.length, 2);
});

test('the price is grouped as the locale writes it and does not break', () => {
  assert.equal(priceFrom(null, 'ru'), null);
  assert.equal(priceFrom(290, 'ru'), '290');
  assert.equal(priceFrom(1290, 'ru'), '1 290');
  assert.equal(priceFrom(1290, 'en'), '1,290');
});

test('the sheet names the contact by its handle, or not at all', () => {
  assert.equal(handleOf('https://t.me/konnekt_ads'), '@konnekt_ads');
  assert.equal(handleOf('https://example.test/ads'), null);
});
