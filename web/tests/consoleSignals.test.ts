import assert from 'node:assert/strict';
import { test } from 'node:test';

import { menuCounts, type Signals } from '../src/console/signals.ts';

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
    },
  ],
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
