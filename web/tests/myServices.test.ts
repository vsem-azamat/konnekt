import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  allPaused,
  asInput,
  keepsListed,
  liveCount,
  offersWith,
  whatToAdd,
  withPaused,
} from '../src/lib/myServices.ts';
import type { MyHelper, MyOffer } from '../src/lib/types.ts';

function offer(id: number, extra: Partial<MyOffer> = {}): MyOffer {
  return {
    id,
    service_type_id: 1,
    service_type: 'tutoring',
    service_type_name: 'Репетиторство',
    subject_id: id * 10,
    subject_name: `Предмет ${id}`,
    institution_id: 2,
    institution_name: 'ČVUT',
    price_amount: 600,
    price_unit: 'hour',
    langs: ['ru'],
    option_ids: [3],
    note: 'заметка',
    turnaround_days: null,
    paused: false,
    ...extra,
  };
}

function helper(status: string, offers: MyOffer[] = []): MyHelper {
  return {
    exists: true,
    status,
    headline: null,
    about: null,
    work_format: 'both',
    city: null,
    place_note: null,
    offers,
  };
}

test('an offer goes back with everything this screen does not edit', () => {
  assert.deepEqual(asInput(offer(1)), {
    service_type_id: 1,
    subject_id: 10,
    institution_id: 2,
    price_amount: 600,
    price_unit: 'hour',
    langs: ['ru'],
    option_ids: [3],
    note: 'заметка',
    turnaround_days: null,
  });
});

test('the pause is not sent, so a save never switches a service back on', () => {
  assert.equal('paused' in asInput(offer(1, { paused: true })), false);
});

test('a new price replaces only the offer it was set on', () => {
  const sent = offersWith([offer(1), offer(2)], 2, {
    price_amount: 750,
    price_unit: 'lesson',
  });
  assert.deepEqual(
    sent.map((row) => [row.subject_id, row.price_amount, row.price_unit]),
    [
      [10, 600, 'hour'],
      [20, 750, 'lesson'],
    ],
  );
});

test('a removed offer is left out of the list, which is authoritative', () => {
  const sent = offersWith([offer(1), offer(2)], 1, null);
  assert.deepEqual(
    sent.map((row) => row.subject_id),
    [20],
  );
});

test('saving a service keeps the profile where it stands in the catalog', () => {
  // `publish` is not optional on the server: left out it reads as false, and
  // a price fixed on a listed profile would take the profile down.
  assert.equal(keepsListed(helper('published')), true);
  assert.equal(keepsListed(helper('hidden')), false);
  assert.equal(keepsListed(helper('draft')), false);
  // A banned profile ignores the flag; true, so it cannot read as a request to hide.
  assert.equal(keepsListed(helper('banned')), true);
});

test('a switch flipped shows at once on that service alone', () => {
  const before = helper('published', [offer(1), offer(2)]);
  const after = withPaused(before, 2, true);
  assert.deepEqual(
    after.offers.map((row) => row.paused),
    [false, true],
  );
  assert.equal(before.offers[1]?.paused, false);
});

test('every service switched off means nobody finds the profile', () => {
  assert.equal(
    allPaused(helper('published', [offer(1, { paused: true }), offer(2)])),
    false,
  );
  assert.equal(
    allPaused(
      helper('published', [offer(1, { paused: true }), offer(2, { paused: true })]),
    ),
    true,
  );
  // No services is its own hint, not this one.
  assert.equal(allPaused(helper('published')), false);
});

test('the count on «Профиль» leaves out switched-off services', () => {
  assert.equal(
    liveCount(helper('published', [offer(1, { paused: true }), offer(2), offer(3)])),
    2,
  );
  assert.equal(liveCount(helper('published', [offer(1, { paused: true })])), 0);
});

test('what to add: a subject where the service needs one, a price, a line under the name', () => {
  const bare = {
    ...helper('published', [
      offer(1, { subject_id: null, subject_name: null, price_amount: null }),
    ]),
    headline: null,
  };
  assert.deepEqual(whatToAdd(bare, new Set([1])), ['subject', 'price', 'headline']);
});

test('what to add: nothing once each is there, and «договорная» counts as a price', () => {
  const full = {
    ...helper('published', [offer(1, { price_amount: null, price_unit: 'negotiable' })]),
    headline: 'ČVUT FEL',
  };
  assert.deepEqual(whatToAdd(full, new Set([1])), []);
});

test('what to add: a service that takes no subject is not asked for one, and a paused one is not asked at all', () => {
  const h = {
    ...helper('published', [
      offer(1, { service_type_id: 7, subject_id: null }),
      offer(2, { subject_id: null, price_amount: null, paused: true }),
    ]),
    headline: 'x',
  };
  assert.deepEqual(whatToAdd(h, new Set([1])), []);
});
