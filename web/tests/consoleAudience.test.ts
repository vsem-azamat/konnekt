import assert from 'node:assert/strict';
import { test } from 'node:test';

import { type AudienceFilters, audiencePath, reachOf } from '../src/console/audience.ts';

test('the list address carries only the filters that are set', () => {
  const none: AudienceFilters = {};
  assert.equal(audiencePath(none, null), '/api/audience?limit=50');
  assert.equal(
    audiencePath(
      { touchpoint: 'mini_app', status: 'reachable', q: ' @anna ', new_days: 7 },
      'c1',
    ),
    '/api/audience?touchpoint=mini_app&status=reachable&q=%40anna&new_days=7&limit=50&cursor=c1',
  );
});

test("a bot's reach reads as can write, blocked or never opened", () => {
  const reach = [
    { bot: 'main_bot', started_at: '2026-03-03T10:11:00', blocked_at: null },
    {
      bot: 'contact_bot',
      started_at: '2026-03-03T10:11:00',
      blocked_at: '2026-04-01T00:00:00',
    },
  ];
  assert.equal(reachOf(reach, 'main_bot'), 'open');
  assert.equal(reachOf(reach, 'contact_bot'), 'blocked');
  assert.equal(reachOf([], 'main_bot'), 'never');
});
