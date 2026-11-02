import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  type AudienceTrends,
  barsOf,
  change,
  comparableFrom,
  overlap,
  percent,
  periodLength,
  splitPeriods,
  type TrendPoint,
} from '../src/console/trends.ts';

function point(from: string, starts: number | null): TrendPoint {
  return { from, to: from, starts, app_new: 0, joins: 0, blocks: 0 };
}

test('the series is the period before, then this one, as many bars each', () => {
  const trends = {
    series: [
      point('2026-11-01', 1),
      point('2026-11-02', 2),
      point('2026-11-03', 3),
      point('2026-11-04', 4),
    ],
  } as AudienceTrends;
  const { now, before } = splitPeriods(trends);
  assert.deepEqual(
    before.map((p) => p.from),
    ['2026-11-01', '2026-11-02'],
  );
  assert.deepEqual(
    barsOf(now, 'starts').map((b) => b.value),
    [3, 4],
  );
});

test('a change needs both periods counted, and a share only when there was something before', () => {
  assert.equal(change(5, null), null);
  assert.deepEqual(change(5, 4), { diff: 1, share: 0.25 });
  assert.deepEqual(change(3, 0), { diff: 3, share: null });
});

test('a comparison starts two whole periods after the record began, in weeks past a month', () => {
  assert.equal(comparableFrom('2026-10-20', 7), '2026-11-03');
  assert.equal(comparableFrom('2026-10-20', 30), '2026-12-19');
  // 90 days are 13 weeks: 91 days a period.
  assert.equal(comparableFrom('2026-11-02', 90), '2027-05-03');
});

test('who came is the bot only, both, and the Mini App without /start, each once', () => {
  const parts = overlap({
    seen_in_chats: 0,
    started_bot: 58,
    opened_app: 62,
    both: 32,
    not_from_chats: 0,
    reachable: 0,
    blocked: 0,
    opted_out: 0,
    estimate: 0,
  });
  assert.deepEqual(parts, { botOnly: 26, both: 32, appOnly: 30, total: 88 });
});

test('a small share keeps one decimal and nothing is a share of nobody', () => {
  assert.equal(percent(88, 2460, 'en'), '3.6%');
  assert.equal(percent(50, 100, 'en'), '50%');
  assert.equal(percent(1, 0, 'en'), '—');
});

test('a period past a month is whole weeks', () => {
  assert.equal(periodLength(7), 7);
  assert.equal(periodLength(30), 30);
  assert.equal(periodLength(90), 91);
});
