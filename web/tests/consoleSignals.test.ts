import assert from 'node:assert/strict';
import { test } from 'node:test';

import { ConsoleError } from '../src/console/session.ts';
import {
  decisionProblem,
  elapsed,
  menuCounts,
  minutesSince,
  minutesUntil,
  type Signals,
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
  pending_actions: [
    {
      id: 2,
      action: 'ban',
      chat_id: null,
      chat_title: null,
      target_user_id: 7,
      target_username: null,
      target_name: null,
      reason: null,
      created_at: '2026-10-22T08:00:00',
      expires_at: '2026-10-22T09:00:00',
    },
  ],
  queues: { ads_unreviewed: 4, chats_in_review: 2 },
};

test('each menu item counts what waits behind it', () => {
  assert.deepEqual(menuCounts(signals, { profiles_to_review: 3 }), {
    signals: 2,
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

test('a refused decision says why, in the words webapi gives', () => {
  assert.equal(decisionProblem(new ConsoleError(409, 'failed', 'gone')), 'gone');
  assert.equal(decisionProblem(new ConsoleError(404, 'failed', 'no such wave')), 'gone');
  assert.equal(
    decisionProblem(new ConsoleError(409, 'failed', 'decided otherwise')),
    'decided',
  );
  assert.equal(
    decisionProblem(new ConsoleError(409, 'failed', 'protected')),
    'protected',
  );
  assert.equal(
    decisionProblem(new ConsoleError(409, 'failed', 'unmanaged')),
    'unmanaged',
  );
  // Telegram refused, or the network did: nothing more specific to say.
  assert.equal(decisionProblem(new ConsoleError(502, 'failed', 'failed')), 'failed');
  assert.equal(decisionProblem(new TypeError('fetch failed')), 'failed');
});
