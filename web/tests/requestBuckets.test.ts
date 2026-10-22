import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buckets, daysLeft, localDay } from '../src/lib/requestBuckets.ts';
import type { HelpRequest, RequestStatus } from '../src/lib/types.ts';

function request(id: number, status: RequestStatus): HelpRequest {
  return {
    id,
    text: 'нужен репетитор',
    subject: null,
    institution: null,
    service_type: null,
    deadline_on: null,
    status,
    responses_count: 0,
    responders: [],
    created_at: '2026-10-01T10:00:00Z',
    expires_at: null,
    closed_at: null,
    helpers_seeing: 0,
  };
}

test('an open request waits in «Открытые», a closed or expired one is in «Закрытые»', () => {
  const { open, closed } = buckets([
    request(1, 'open'),
    request(2, 'closed'),
    request(3, 'expired'),
    request(4, 'open'),
  ]);
  assert.deepEqual(
    open.map((row) => row.id),
    [1, 4],
  );
  assert.deepEqual(
    closed.map((row) => row.id),
    [2, 3],
  );
});

test('a draft has not been asked yet, so it is in neither', () => {
  const { open, closed } = buckets([request(1, 'draft')]);
  assert.equal(open.length + closed.length, 0);
});

const NOW = new Date('2026-10-22T15:00:00Z');

test('the days left count a part of a day as a day', () => {
  assert.equal(daysLeft('2026-11-17T09:00:00Z', NOW), 26);
  assert.equal(daysLeft('2026-10-22T16:00:00Z', NOW), 1);
});

test('a request past its end has no days left, not fewer than none', () => {
  assert.equal(daysLeft('2026-10-20T10:00:00Z', NOW), 0);
});

test('an instant is shown as the day it falls on where the reader is', () => {
  assert.equal(localDay('2026-10-10T10:00:00Z'), '2026-10-10');
  // Kept in a reader's own calendar: a request closed at 23:30 in Prague
  // closed that day, not the next one in UTC.
  const late = new Date(2026, 9, 10, 23, 30);
  assert.equal(localDay(late.toISOString()), '2026-10-10');
});
