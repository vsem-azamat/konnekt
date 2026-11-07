import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  duration,
  heatGrid,
  position,
  shareOf,
  sourceKind,
} from '../src/console/usage.ts';

test('a session reads as minutes and seconds, an hour and more with hours', () => {
  assert.equal(duration(0), '0:00');
  assert.equal(duration(160), '2:40');
  assert.equal(duration(59.6), '1:00');
  assert.equal(duration(3900), '1:05:00');
  assert.equal(duration(-5), '0:00');
});

test('the week is every hour, Monday first, levels in quarters of the busiest hour', () => {
  const grid = heatGrid([
    { weekday: 0, hour: 10, people: 8 },
    { weekday: 6, hour: 23, people: 1 },
    { weekday: 2, hour: 14, people: 4 },
  ]);
  assert.equal(grid.length, 7);
  assert.ok(grid.every((row) => row.length === 24));
  assert.equal(grid[0]?.[10]?.level, 4);
  assert.equal(grid[2]?.[14]?.level, 2);
  // One person in a quiet hour still shows.
  assert.equal(grid[6]?.[23]?.level, 1);
  assert.equal(grid[3]?.[3]?.level, 0);
});

test('a week nobody came is all empty, not a division by zero', () => {
  assert.ok(
    heatGrid([])
      .flat()
      .every((cell) => cell.level === 0 && cell.people === 0),
  );
});

test('a start parameter says what kind of link it was', () => {
  assert.deepEqual(sourceKind(null), { kind: 'none' });
  assert.deepEqual(sourceKind(''), { kind: 'none' });
  assert.deepEqual(sourceKind('site_article_nostrifikace'), {
    kind: 'article',
    slug: 'nostrifikace',
  });
  assert.deepEqual(sourceKind('site_hero'), { kind: 'site', place: 'hero' });
  assert.deepEqual(sourceKind('uni-cvut'), { kind: 'university', code: 'cvut' });
  assert.deepEqual(sourceKind('welcome'), { kind: 'link', key: 'welcome' });
});

test('a position keeps one decimal in the reader’s way, a share needs a whole', () => {
  assert.equal(position(5.55, 'ru'), '5,6');
  assert.equal(position(3, 'en'), '3');
  assert.equal(shareOf(1, 4), 25);
  assert.equal(shareOf(1, 0), null);
});
