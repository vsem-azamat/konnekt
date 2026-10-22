import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  dayCells,
  localHeatmap,
  memberChange,
  memberTrend,
  parentChoices,
  signed,
} from '../src/console/activity.ts';
import type { ConsoleChat } from '../src/console/session.ts';

test('the heatmap is read in local time, so a Prague evening is not UTC afternoon', () => {
  // Monday 18:00 UTC is Monday 20:00 in Prague summer time.
  const { grid, max } = localHeatmap([{ weekday: 0, hour: 18, count: 5 }], 120);
  assert.equal(grid[0]?.[20], 5);
  assert.equal(grid[0]?.[18], 0);
  assert.equal(max, 5);
});

test('an hour pushed past Sunday midnight lands on Monday', () => {
  const { grid } = localHeatmap([{ weekday: 6, hour: 23, count: 2 }], 120);
  assert.equal(grid[0]?.[1], 2);
});

test('west of Greenwich an early Monday hour goes back to Sunday', () => {
  const { grid } = localHeatmap([{ weekday: 0, hour: 1, count: 3 }], -300);
  assert.equal(grid[6]?.[20], 3);
});

test('an empty week has nothing to scale by', () => {
  const { grid, max } = localHeatmap([], 0);
  assert.equal(max, 0);
  assert.equal(grid.length, 7);
  assert.ok(grid.every((day) => day.length === 24 && day.every((n) => n === 0)));
});

test('a trend needs two counts, and says how far it moved', () => {
  assert.equal(
    memberTrend([{ captured_at: '2026-09-01T00:00:00', member_count: 10 }]),
    null,
  );
  const trend = memberTrend([
    { captured_at: '2026-09-01T00:00:00', member_count: 100 },
    { captured_at: '2026-09-02T00:00:00', member_count: 120 },
    { captured_at: '2026-09-03T00:00:00', member_count: 110 },
  ]);
  assert.ok(trend);
  assert.equal(trend.change, 10);
  assert.equal(trend.first, 100);
  assert.equal(trend.last, 110);
  // Lowest count at the bottom edge, highest at the top.
  assert.equal(trend.points, '0,32 50,0 100,16');
});

test('a flat trend is drawn through the middle, not along an edge', () => {
  const trend = memberTrend([
    { captured_at: '2026-09-01T00:00:00', member_count: 50 },
    { captured_at: '2026-09-02T00:00:00', member_count: 50 },
  ]);
  assert.equal(trend?.points, '0,16 100,16');
});

function chat(id: number, title: string, parent: number | null = null): ConsoleChat {
  return {
    id,
    title,
    resource_status: 'approved',
    member_count: null,
    public_link: null,
    parent_chat_id: parent,
    institution_code: null,
    city: null,
    topic: null,
    join_mode: 'admins',
    join_by_request: null,
    is_welcome_enabled: false,
    is_service_cleanup_enabled: false,
  };
}

test('a chat goes under a top-level chat, never under itself or a child', () => {
  const chats = [
    chat(1, 'ČVUT'),
    chat(2, 'ČVUT FIT', 1),
    chat(3, 'VŠE'),
    chat(4, 'Flood'),
    chat(5, 'Anglická', null),
  ];
  assert.deepEqual(
    parentChoices(chats, 4).map((c) => c.id),
    [5, 1, 3],
  );
  // A child is never offered: the list groups one level deep.
  assert.ok(!parentChoices(chats, 3).some((c) => c.id === 2));
});

test('a chat others sit under cannot go under anything', () => {
  const chats = [chat(1, 'ČVUT'), chat(2, 'ČVUT FIT', 1), chat(3, 'VŠE')];
  assert.deepEqual(parentChoices(chats, 1), []);
});

test('a half-hour zone moves by the whole hours in it, either side of Greenwich', () => {
  assert.equal(localHeatmap([{ weekday: 0, hour: 10, count: 1 }], 330).grid[0]?.[15], 1);
  assert.equal(localHeatmap([{ weekday: 0, hour: 10, count: 1 }], -210).grid[0]?.[7], 1);
});

test('a chat under one parent may move under another', () => {
  const chats = [chat(1, 'ČVUT'), chat(2, 'ČVUT FIT', 1), chat(3, 'VŠE')];
  assert.deepEqual(
    parentChoices(chats, 2).map((c) => c.id),
    [1, 3],
  );
});

test('the members moved by what every counted chat moved, where it is known', () => {
  const entry = (delta_24h: number | null, delta_7d: number | null) => ({
    chat_id: -1,
    title: null,
    current: 100,
    delta_24h,
    delta_7d,
  });
  assert.deepEqual(memberChange([entry(5, 30), entry(-2, null), entry(null, 4)]), {
    day: 3,
    week: 34,
  });
  assert.deepEqual(memberChange([entry(null, null)]), { day: null, week: null });
  assert.deepEqual(memberChange([]), { day: null, week: null });
});

test('a day by hour folds into eight three-hour cells of the reader’s day', () => {
  const hours = Array<number>(24).fill(0);
  hours[0] = 1; // 00 UTC
  hours[22] = 2; // 22 UTC
  hours[23] = 3; // 23 UTC
  // UTC: 00–02 holds 1, 21–23 holds 5.
  assert.deepEqual(dayCells(hours, 0), [1, 0, 0, 0, 0, 0, 0, 5]);
  // Prague in summer, UTC+2: 22 and 23 UTC are 00 and 01, 00 UTC is 02.
  assert.deepEqual(dayCells(hours, 120), [6, 0, 0, 0, 0, 0, 0, 0]);
});

test('west of Greenwich a day folds back, and a half-hour zone moves by its whole hours', () => {
  const hours = Array<number>(24).fill(0);
  hours[1] = 4; // 01 UTC
  // New York in winter, UTC−5: 01 UTC is 20 the evening before.
  assert.deepEqual(dayCells(hours, -300), [0, 0, 0, 0, 0, 0, 4, 0]);
  // India, UTC+5:30, moves by five: 01 UTC is 06.
  assert.deepEqual(dayCells(hours, 330), [0, 0, 4, 0, 0, 0, 0, 0]);
});

test('a change is written with its sign, a true minus, and ± for none', () => {
  const format = (n: number) => String(n);
  assert.equal(signed(37, format), '+37');
  assert.equal(signed(-5, format), '−5');
  assert.equal(signed(0, format), '±0');
});
