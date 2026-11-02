import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ConsoleError } from '../src/console/session.ts';
import {
  decisionProblem,
  elapsed,
  menuCounts,
  minutesSince,
  minutesUntil,
  queues,
  type Signals,
  waited,
} from '../src/console/signals.ts';

const signals: Signals = {
  waves: [
    {
      id: 1,
      chat_id: -100,
      chat_title: 'Matfyz',
      member_count: 461,
      started_at: '2026-10-22T08:00:00',
      last_surge_at: '2026-10-22T08:10:00',
      held: 64,
      paused: true,
      quiet_until: '2026-10-22T08:25:00',
    },
  ],
  wave_per_minute: 20,
  queues: {
    ads_unreviewed: 4,
    ads_waiting_since: '2026-10-20T08:00:00',
    chats_in_review: 2,
    chats_waiting_since: '2026-08-09T18:07:35',
  },
};

test('each menu item counts what waits behind it', () => {
  assert.deepEqual(menuCounts(signals, { profiles_to_review: 3 }), {
    signals: 1,
    chats: 2,
    spam: 4,
    catalog: 3,
  });
});

test('a count that has not arrived is no badge, not a guess', () => {
  assert.deepEqual(menuCounts(undefined, undefined), {
    signals: 0,
    chats: 0,
    spam: 0,
    catalog: 0,
  });
});

test('webapi times are UTC, whatever zone the reader is in', () => {
  // In UTC itself a time read as local would pass too.
  const zone = process.env.TZ;
  process.env.TZ = 'America/New_York';
  try {
    const now = new Date('2026-10-22T08:30:00Z');
    assert.equal(minutesSince('2026-10-22T08:24:10', now), 5);
    assert.equal(minutesSince('2026-10-22T08:31:00', now), 0);
    // A started minute is a minute left: «0 мин» while the pause still holds is wrong.
    assert.equal(minutesUntil('2026-10-22T08:39:10', now), 10);
    assert.equal(minutesUntil('2026-10-22T08:29:00', now), 0);
  } finally {
    if (zone === undefined) delete process.env.TZ;
    else process.env.TZ = zone;
  }
});

test('how long ago reads in minutes, then in hours', () => {
  const now = new Date('2026-10-22T08:30:00Z');
  assert.deepEqual(elapsed('2026-10-22T08:29:30', now), { unit: 'now' });
  assert.deepEqual(elapsed('2026-10-22T07:31:00', now), { unit: 'minutes', count: 59 });
  // A wave is kept a day: «1380 мин назад» is unreadable.
  assert.deepEqual(elapsed('2026-10-21T09:30:00', now), { unit: 'hours', count: 23 });
});

test('each queue with something in it says how many and since when', () => {
  assert.deepEqual(
    queues(signals, {
      profiles_to_review: 0,
      profiles_waiting_since: null,
      unanswered: 3,
      unanswered_waiting_since: '2026-10-01T10:00:00Z',
    }),
    [
      { key: 'ads', count: 4, since: '2026-10-20T08:00:00' },
      { key: 'review', count: 2, since: '2026-08-09T18:07:35' },
      { key: 'requests', count: 3, since: '2026-10-01T10:00:00Z' },
    ],
  );
  // The catalog not answered yet: its queues wait for it, webapi's do not.
  assert.deepEqual(
    queues(signals, undefined).map((queue) => queue.key),
    ['ads', 'review'],
  );
  assert.deepEqual(queues(undefined, undefined), []);
});

test('how long the oldest waits reads in hours, then in days', () => {
  const now = new Date('2026-10-22T08:30:00Z');
  assert.deepEqual(waited('2026-10-22T08:00:00', now), { unit: 'fresh' });
  assert.deepEqual(waited('2026-10-22T07:30:00', now), { unit: 'hours', count: 1 });
  // «1 день» for 47 hours would hide most of a day.
  assert.deepEqual(waited('2026-10-20T09:30:00', now), { unit: 'hours', count: 47 });
  assert.deepEqual(waited('2026-10-20T08:30:00', now), { unit: 'days', count: 2 });
  assert.deepEqual(waited('2026-08-09T18:07:35', now), { unit: 'days', count: 73 });
  // The catalog's times carry their zone, webapi's are UTC without one.
  assert.deepEqual(waited('2026-10-22T09:00:00+02:00', now), { unit: 'hours', count: 1 });
});

test('a refused decision says why, in the words webapi gives', () => {
  assert.equal(decisionProblem(new ConsoleError(404, 'failed', 'no such wave')), 'gone');
  assert.equal(
    decisionProblem(new ConsoleError(409, 'failed', 'decided otherwise')),
    'decided',
  );
  // The network or a gateway: nothing more specific to say; another try is the honest advice.
  assert.equal(decisionProblem(new ConsoleError(502)), 'failed');
  assert.equal(decisionProblem(new ConsoleError(500)), 'failed');
  assert.equal(decisionProblem(new TypeError('fetch failed')), 'failed');
});
