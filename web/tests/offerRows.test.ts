import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  addAxis,
  applyPriceChip,
  type Draft,
  dropRow,
  keyOf,
  priceChipOn,
  serviceAnswers,
  typedPrice,
} from '../src/lib/offerRows.ts';

/** A row of the service the tests use, with everything filled in. */
function row(over: Partial<Draft> = {}): Draft {
  return {
    key: '7:12:null',
    service_type_id: 7,
    subject_id: 12,
    subject_name: 'Математический анализ',
    institution_id: null,
    institution_name: null,
    option_ids: [3, 4],
    note: 'Разбираю задачи с прошлых экзаменов',
    turnaround_days: 3,
    price: '500',
    unit: 'hour',
    langs: ['ru'],
    ...over,
  };
}

test('a second subject starts from what the service already says', () => {
  // Every answer that belongs to the service, the turnaround included: a
  // person who set «за 3 дня» and then added a second subject would otherwise
  // publish one row promising three days and one promising nothing.
  assert.deepEqual(serviceAnswers([row()], 7), {
    price: '500',
    unit: 'hour',
    option_ids: [3, 4],
    note: 'Разбираю задачи с прошлых экзаменов',
    turnaround_days: 3,
  });
});

test('a service with no row yet inherits nothing', () => {
  assert.deepEqual(serviceAnswers([row()], 9), {});
});

test('a service with other rows left simply loses the one removed', () => {
  const kept = row({
    key: '7:13:null',
    subject_id: 13,
    subject_name: 'Линейная алгебра',
  });
  assert.deepEqual(dropRow([row(), kept], row(), 'subject'), [kept]);
});

test('the last row of a service stays, with its axes cleared', () => {
  const [last, ...rest] = dropRow([row()], row(), 'subject');
  assert.equal(rest.length, 0);
  assert.equal(last?.service_type_id, 7);
  assert.equal(last?.subject_id, null);
  assert.equal(last?.subject_name, null);
});

test('and keeps what the person said about the service itself', () => {
  // The checklist, the note, the turnaround and the price belong to the
  // service type, not to one of its rows — see catalog/docs/data-model.md. Tapping a
  // subject chip off is not an answer to any of those questions.
  const [last] = dropRow([row()], row(), 'subject');
  assert.deepEqual(last?.option_ids, [3, 4]);
  assert.equal(last?.note, 'Разбираю задачи с прошлых экзаменов');
  assert.equal(last?.turnaround_days, 3);
  assert.equal(last?.price, '500');
  assert.deepEqual(last?.langs, ['ru']);
});

test('a row that also names a school keeps it when the subject goes', () => {
  // One row can carry both axes — a school picked first and a subject after it
  // fill the same row — and the chip that was tapped is the only answer being
  // taken back.
  const both = row({ institution_id: 4, institution_name: 'ČVUT' });
  const [left, ...rest] = dropRow([both], both, 'subject');
  assert.equal(rest.length, 0);
  assert.equal(left?.subject_id, null);
  assert.equal(left?.institution_id, 4);
  assert.equal(left?.institution_name, 'ČVUT');
});

test('and keeps the subject when the school goes', () => {
  const both = row({ institution_id: 4, institution_name: 'ČVUT' });
  const [left] = dropRow([both], both, 'institution');
  assert.equal(left?.institution_id, null);
  assert.equal(left?.subject_id, 12);
});

test('a row with both axes goes only when both are gone', () => {
  // The service has another row, so nothing has to be kept for its sake.
  const both = row({ institution_id: 4, institution_name: 'ČVUT' });
  const other = row({ key: '7:13:null', subject_id: 13, subject_name: 'Физика' });
  // Two taps, the second on the row as it stands after the first — which is
  // what the chip the screen renders carries.
  const once = dropRow([both, other], both, 'subject');
  const school = once.find((candidate) => candidate.institution_id === 4);
  assert.ok(school);
  assert.deepEqual(dropRow(once, school, 'institution'), [other]);
});

test('a cleared row is re-keyed from what it still holds', () => {
  // The key names the row's axes, and `addAxis` mints keys the same way. A row
  // still called `7:12` after subject 12 was cleared is one the picker can
  // mint again — two rows, one key, and a duplicate the server refuses.
  const both = row({ key: '7:12', institution_id: 4, institution_name: 'ČVUT' });
  const [kept] = dropRow([both], both, 'subject');
  assert.equal(kept?.key, '7:null:4');

  const [bare] = dropRow([row()], row(), 'subject');
  assert.equal(bare?.key, '7:null:null');
});

test('a cleared row that duplicates another one goes instead', () => {
  // Two rows of one service at the same school, the first already cleared of
  // its subject. Clearing the second's would name the same pair, which
  // `offers` is unique on: two rows for one offer, sharing a key and a price
  // field, and a save the server refuses.
  const shared = { institution_id: 4, institution_name: 'ČVUT' };
  const cleared = row({
    key: '7:null:4',
    subject_id: null,
    subject_name: null,
    ...shared,
  });
  const second = row({
    key: '7:13:4',
    subject_id: 13,
    subject_name: 'Физика',
    ...shared,
  });
  assert.deepEqual(dropRow([cleared, second], second, 'subject'), [cleared]);
});

/** A row of a service nothing has been said about yet. */
function blank(over: Partial<Draft> = {}): Draft {
  const empty: Draft = {
    key: '',
    service_type_id: 7,
    subject_id: null,
    subject_name: null,
    institution_id: null,
    institution_name: null,
    option_ids: [],
    note: '',
    turnaround_days: null,
    price: '',
    unit: 'hour',
    langs: [],
    ...over,
  };
  return { ...empty, key: keyOf(empty) };
}

test('the first axis of a service fills its empty row', () => {
  const rows = addAxis([blank()], blank(), 'subject', { id: 12, name: 'Матан' });
  assert.equal(rows.length, 1);
  assert.equal(rows[0]?.subject_id, 12);
});

test('a filled row is re-keyed, or the next one can be minted onto it', () => {
  // The defect this pins: filling a row without re-keying leaves the key
  // naming axes the row no longer has, and `keyOf` can then mint it again for
  // a different row — two rows, one key, one price field between them.
  const rows = addAxis([blank()], blank(), 'institution', { id: 4, name: 'ČVUT' });
  assert.equal(rows[0]?.key, keyOf(rows[0] as Draft));
  assert.equal(new Set(rows.map((r) => r.key)).size, rows.length);
});

test('a second axis is added, and starts from what the service says', () => {
  const rows = addAxis([row()], blank(), 'subject', { id: 13, name: 'Физика' });
  assert.equal(rows.length, 2);
  assert.equal(rows[1]?.price, '500');
  assert.deepEqual(rows[1]?.option_ids, [3, 4]);
  assert.equal(rows[1]?.turnaround_days, 3);
  assert.equal(rows[1]?.key, '7:13:null');
});

test('every row of a service keeps a key of its own through both moves', () => {
  // The trace a review found: fill, clear, fill again, clear again.
  let rows = [
    row({ key: '7:12:5', institution_id: 5, institution_name: 'ČVUT' }),
    row({ key: '7:12:9', institution_id: 9, institution_name: 'VŠE' }),
  ];
  const first = rows[0] as Draft;
  rows = dropRow(rows, first, 'institution');
  const emptied = rows.find((candidate) => candidate.institution_id === null) as Draft;
  assert.ok(emptied);
  rows = addAxis(rows, blank(), 'institution', { id: 7, name: 'UK' });
  const second = rows.find((candidate) => candidate.institution_id === 9) as Draft;
  rows = dropRow(rows, second, 'institution');
  assert.equal(new Set(rows.map((r) => r.key)).size, rows.length);
  for (const candidate of rows) assert.equal(candidate.key, keyOf(candidate));
});

test('a price chip prices every row of the service while they agree', () => {
  const rows = [row({ price: '' }), row({ key: '7:13:null', subject_id: 13, price: '' })];
  const after = applyPriceChip(rows, 7, '400', 'hour');
  assert.deepEqual(
    after.map((r) => r.price),
    ['400', '400'],
  );
});

test('a price chip leaves a subject that has its own price alone', () => {
  // Calculus at 500, physics at 700: the chip must not erase the 700.
  const rows = [
    row({ price: '500' }),
    row({ key: '7:13:null', subject_id: 13, price: '700' }),
    row({ key: '7:14:null', subject_id: 14, price: '' }),
    row({ key: '8:1:null', service_type_id: 8, subject_id: 1, price: '900' }),
  ];
  const after = applyPriceChip(rows, 7, '400', 'hour');
  assert.deepEqual(
    after.map((r) => r.price),
    ['500', '700', '400', '900'],
  );
});

test('a price chip reads as chosen only when every row of the service says it', () => {
  const two = [
    row({ price: '500' }),
    row({ key: '7:13:null', subject_id: 13, price: '700' }),
  ];
  assert.equal(priceChipOn(two, 7, '500', 'hour'), false);
  assert.equal(priceChipOn([row({ price: '500' })], 7, '500', 'hour'), true);
  assert.equal(
    priceChipOn([row({ price: '500', unit: 'lesson' })], 7, '500', 'hour'),
    false,
  );
});

test('«договоримся» is chosen while nothing is priced, as the screen promises', () => {
  assert.equal(priceChipOn([row({ price: '' })], 7, '', 'negotiable'), true);
  assert.equal(priceChipOn([row({ price: '500' })], 7, '', 'negotiable'), false);
});

test('a number typed after «договоримся» goes back to a unit it can be per', () => {
  assert.deepEqual(
    typedPrice(row({ price: '', unit: 'negotiable' }), '600', 'hour'),
    row({ price: '600', unit: 'hour' }),
  );
  assert.equal(typedPrice(row({ unit: 'lesson' }), '600', 'hour').unit, 'lesson');
});
