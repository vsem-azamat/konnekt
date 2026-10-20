import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  type AudienceFilters,
  audiencePath,
  bars,
  reachOf,
  reachSegments,
  topLanguages,
} from '../src/console/audience.ts';

test('the reach bar keeps the four statuses in one order and drops empty ones', () => {
  const segments = reachSegments({
    reachable: 912,
    never_started: 241,
    blocked: 0,
    opted_out: 33,
  });
  assert.deepEqual(
    segments.map((s) => [s.status, s.count]),
    [
      ['reachable', 912],
      ['never_started', 241],
      ['opted_out', 33],
    ],
  );
});

test('bars are sized against the largest and listed largest first', () => {
  const rows = bars({ main_bot: 796, mini_app: 347, contact_bot: 81, moved_bot: 0 });
  assert.deepEqual(
    rows.map((r) => [r.key, r.count, Math.round(r.share * 100)]),
    [
      ['main_bot', 796, 100],
      ['mini_app', 347, 44],
      ['contact_bot', 81, 10],
      ['moved_bot', 0, 0],
    ],
  );
});

test('languages past the first few are summed as the rest', () => {
  const languages = [
    { code: 'ru', count: 704 },
    { code: 'uk', count: 251 },
    { code: 'cs', count: 168 },
    { code: 'en', count: 97 },
    { code: 'de', count: 40 },
    { code: 'pl', count: 24 },
  ];
  assert.deepEqual(topLanguages(languages, 4), {
    top: languages.slice(0, 4),
    rest: 64,
  });
  assert.deepEqual(topLanguages(languages.slice(0, 2), 4), {
    top: languages.slice(0, 2),
    rest: 0,
  });
});

test('the list address carries only the filters that are set', () => {
  const none: AudienceFilters = {};
  assert.equal(audiencePath(none, 0), '/api/audience?limit=50&offset=0');
  assert.equal(
    audiencePath({ touchpoint: 'mini_app', status: 'reachable', q: ' @anna ' }, 50),
    '/api/audience?touchpoint=mini_app&status=reachable&q=%40anna&limit=50&offset=50',
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
