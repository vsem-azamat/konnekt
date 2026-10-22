import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  chipKey,
  defaultChip,
  type FeedChip,
  feedChips,
  feedQuery,
  feedSections,
} from '../src/lib/feedChips.ts';
import type { FeedFacetsOut } from '../src/lib/generated/types.gen.ts';
import type { FeedRequest } from '../src/lib/types.ts';

function facets(overrides: Partial<FeedFacetsOut> = {}): FeedFacetsOut {
  return {
    all: 14,
    mine: 5,
    subjects: [{ id: 7, name: 'Математика', count: 3 }],
    service_types: [{ id: 2, name: 'Репетиторство', count: 8 }],
    formats: { online: 9, offline: 4 },
    cities: [{ name: 'Praha', count: 6 }],
    budget_upto: [
      { amount: 500, count: 2 },
      { amount: 1000, count: 0 },
    ],
    ...overrides,
  };
}

function chip(key: string): FeedChip {
  const found = feedChips(facets()).find((option) => chipKey(option) === key);
  assert.ok(found, key);
  return found;
}

function row(id: number, onMyServices: boolean, responded = false): FeedRequest {
  return {
    id,
    text: 'нужна помощь',
    subject: null,
    subject_id: null,
    institution: null,
    service_type: null,
    service_type_id: null,
    deadline_on: null,
    status: 'open',
    responses_count: 0,
    created_at: '2026-10-22T10:00:00Z',
    expires_at: null,
    closed_at: null,
    helpers_seeing: 0,
    author: { id: 1, initials: 'НС', tone: 1, photo_url: null },
    author_name: 'Ника',
    budget: null,
    langs: [],
    reason: null,
    on_my_services: onMyServices,
    responded,
  };
}

test('the chips run as the mockup does, each with its count over the whole feed', () => {
  assert.deepEqual(
    feedChips(facets()).map((chip) => [chipKey(chip), chip.count]),
    [
      ['mine', 5],
      ['all', 14],
      ['shelf:7', 3],
      ['online', 9],
      ['city:Praha', 6],
      ['budget:500', 2],
    ],
  );
});

test('a chip that would leave nothing is not offered, but «Все» always is', () => {
  const keys = feedChips(
    facets({
      all: 0,
      mine: 0,
      subjects: [],
      formats: { online: 0, offline: 0 },
      cities: [],
      budget_upto: [
        { amount: 500, count: 0 },
        { amount: 1000, count: 0 },
      ],
    }),
  ).map(chipKey);
  assert.deepEqual(keys, ['all']);
});

test('the feed opens on the helper’s own services, or on everything when none wait', () => {
  assert.equal(chipKey(defaultChip(3)), 'mine');
  assert.equal(chipKey(defaultChip(0)), 'all');
});

test('the chosen chip stays on the row after its requests are gone, so it can be seen and left', () => {
  const praha: FeedChip = { kind: 'city', name: 'Praha', count: 1 };
  const keys = feedChips(facets({ cities: [] }), praha).map(
    (option) => [chipKey(option), option.count] as const,
  );
  assert.deepEqual(keys.at(-1), ['city:Praha', 0]);
  const shelf = chip('shelf:7');
  const kept = feedChips(
    facets({ subjects: [{ id: 7, name: 'Математика', count: 0 }] }),
    shelf,
  );
  assert.deepEqual(
    kept.filter((option) => chipKey(option) === 'shelf:7').map((option) => option.count),
    [0],
  );
});

test('each chip asks the server for its narrowing, answered requests included', () => {
  assert.deepEqual(feedQuery(chip('mine')), { with_responded: true, mine: true });
  assert.deepEqual(feedQuery(chip('all')), { with_responded: true });
  assert.deepEqual(feedQuery(chip('shelf:7')), { with_responded: true, subject_id: 7 });
  assert.deepEqual(feedQuery(chip('online')), {
    with_responded: true,
    work_format: 'online',
  });
  assert.deepEqual(feedQuery(chip('city:Praha')), {
    with_responded: true,
    city: 'Praha',
  });
  assert.deepEqual(feedQuery(chip('budget:500')), {
    with_responded: true,
    budget_upto: 500,
  });
});

test('under «Мои услуги» the list is one, without headings', () => {
  const sections = feedSections([row(1, true), row(2, true)], chip('mine'));
  assert.deepEqual(
    sections.map((section) => [section.heading, section.rows.map((r) => r.id)]),
    [[null, [1, 2]]],
  );
});

test('under any other chip the helper’s own come first, then the rest, each headed', () => {
  const sections = feedSections(
    [row(1, false), row(2, true), row(3, false)],
    chip('all'),
  );
  assert.deepEqual(
    sections.map((section) => [section.heading, section.rows.map((r) => r.id)]),
    [
      ['mine', [2]],
      ['others', [1, 3]],
    ],
  );
});

test('a heading over the only section there is says nothing, so there is none', () => {
  const all = chip('all');
  assert.deepEqual(
    feedSections([row(1, false), row(2, false)], all).map((section) => section.heading),
    [null],
  );
  assert.deepEqual(
    feedSections([row(1, true)], all).map((section) => section.heading),
    [null],
  );
  assert.deepEqual(feedSections([], all), []);
});

test('within each section the answered come after the unanswered, as the server ranks them', () => {
  const sections = feedSections(
    [row(1, true), row(2, false), row(3, true, true), row(4, false, true), row(5, false)],
    chip('all'),
  );
  assert.deepEqual(
    sections.map((section) => section.rows.map((r) => r.id)),
    [
      [1, 3],
      [2, 5, 4],
    ],
  );
});
