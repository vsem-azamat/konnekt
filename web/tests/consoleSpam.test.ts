import assert from 'node:assert/strict';
import { test } from 'node:test';

import type { SpamPing } from '../src/console/session.ts';
import {
  awaitsAnswer,
  byDay,
  nextBefore,
  PAGE,
  pingsPath,
  unreviewedPath,
} from '../src/console/spam.ts';

function ping(id: number, over: Partial<SpamPing> = {}): SpamPing {
  return {
    id,
    chat_id: -1001,
    chat_title: 'IT Чехия',
    user_id: 42,
    username: null,
    first_name: 'Ivan',
    last_name: null,
    blocked: false,
    message_id: 1,
    kind: 'link',
    matches: ['t.me/promo'],
    snippet: null,
    detected_at: '2026-10-20T10:00:00',
    verdict: null,
    ...over,
  };
}

test('the queue asks only for what the filters say', () => {
  assert.equal(
    pingsPath({ status: 'unreviewed', chatId: null, days: null }),
    `/api/spam/pings?limit=${PAGE}&status=unreviewed`,
  );
  assert.equal(
    pingsPath(
      { status: 'all', chatId: -1002, days: 7 },
      { at: '2026-10-20T10:00:00', id: 99 },
    ),
    `/api/spam/pings?limit=${PAGE}&status=all&chat_id=-1002&days=7&before_at=2026-10-20T10%3A00%3A00&before_id=99`,
  );
});

test('the queue’s count is asked under the list’s chat and period', () => {
  assert.equal(
    unreviewedPath({ status: 'all', chatId: null, days: null }),
    '/api/spam/pings/unreviewed?',
  );
  assert.equal(
    unreviewedPath({ status: 'not_ad', chatId: -1002, days: 7 }),
    '/api/spam/pings/unreviewed?chat_id=-1002&days=7',
  );
});

test('another page is asked for only after a full one', () => {
  const full = Array.from({ length: PAGE }, (_, i) => ping(1000 - i));
  assert.deepEqual(nextBefore(full), { at: '2026-10-20T10:00:00', id: 1000 - PAGE + 1 });
  assert.equal(nextBefore(full.slice(1)), undefined);
  assert.equal(nextBefore([]), undefined);
});

test('a hit waits for an answer until it has a verdict', () => {
  assert.equal(awaitsAnswer(ping(1)), true);
  assert.equal(awaitsAnswer(ping(1, { verdict: 'not_ad' })), false);
  assert.equal(awaitsAnswer(ping(1, { verdict: 'done' })), false);
  assert.equal(awaitsAnswer(ping(1, { verdict: 'ad' })), false);
  // A ban that took nowhere answered nothing: the hit still waits.
  assert.equal(awaitsAnswer(ping(1, { blocked: true })), true);
});

test('hits are grouped by the reader’s day, newest day first, in order', () => {
  const now = new Date(2026, 9, 20, 15, 0);
  const at = (day: number, hour: number) => new Date(2026, 9, day, hour).toISOString();
  const groups = byDay(
    [
      ping(5, { detected_at: at(20, 13) }),
      ping(4, { detected_at: at(20, 1) }),
      ping(3, { detected_at: at(19, 23) }),
      ping(2, { detected_at: at(12, 9) }),
    ],
    now,
  );
  assert.deepEqual(
    groups.map((group) => [group.day, group.pings.map((p) => p.id)]),
    [
      ['today', [5, 4]],
      ['yesterday', [3]],
      ['2026-10-12', [2]],
    ],
  );
});
