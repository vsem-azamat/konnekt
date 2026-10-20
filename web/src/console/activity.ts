/** A chat's activity and its place in the list, apart from the screen. */

import type { ConsoleChat, HeatmapCell, MemberDelta, MemberSnapshot } from './session.ts';

const WEEK_HOURS = 7 * 24;

/**
 * Messages per weekday and hour in the reader's own time: webapi counts in
 * UTC, and a Prague evening read as UTC would look like the afternoon.
 * `offsetMinutes` is east of UTC, the opposite sign of getTimezoneOffset().
 *
 * Approximate twice over: a half-hour zone moves by the whole hours in it,
 * and today's offset is applied to the whole week, so a week across a clock
 * change is an hour off for part of it. A grid of busy hours survives both.
 */
export function localHeatmap(
  cells: HeatmapCell[],
  offsetMinutes: number,
): { grid: number[][]; max: number } {
  const week = Array<number>(WEEK_HOURS).fill(0);
  const shift = Math.trunc(offsetMinutes / 60);
  for (const cell of cells) {
    const at =
      (((cell.weekday * 24 + cell.hour + shift) % WEEK_HOURS) + WEEK_HOURS) % WEEK_HOURS;
    week[at] = (week[at] ?? 0) + cell.count;
  }
  const grid = Array.from({ length: 7 }, (_, day) => week.slice(day * 24, day * 24 + 24));
  const max = Math.max(0, ...week);
  return { grid, max };
}

/**
 * A day's messages by UTC hour as eight three-hour cells of the reader's own
 * day, 00–03 first. Approximate as localHeatmap is, and for the same reasons.
 */
export function dayCells(hours: number[], offsetMinutes: number): number[] {
  const cells = Array<number>(8).fill(0);
  const shift = Math.trunc(offsetMinutes / 60);
  hours.forEach((count, hour) => {
    const local = (((hour + shift) % 24) + 24) % 24;
    const at = Math.floor(local / 3);
    cells[at] = (cells[at] ?? 0) + count;
  });
  return cells;
}

/**
 * How far the members moved across every chat, over a day and over a week.
 * A chat counted too recently to compare leaves that window out; none known
 * is none, not zero.
 */
export function memberChange(entries: MemberDelta[]): {
  day: number | null;
  week: number | null;
} {
  const sum = (values: (number | null)[]) => {
    const known = values.filter((value): value is number => value !== null);
    return known.length ? known.reduce((a, b) => a + b, 0) : null;
  };
  return {
    day: sum(entries.map((entry) => entry.delta_24h)),
    week: sum(entries.map((entry) => entry.delta_7d)),
  };
}

/** A change as the summary writes it: +37, −5 (a true minus), ±0. */
export function signed(n: number, format: (n: number) => string): string {
  return `${n > 0 ? '+' : n < 0 ? '−' : '±'}${format(Math.abs(n))}`;
}

/**
 * Member counts as a line 100 wide and 32 high, oldest on the left, with how
 * far the count moved. Nothing to draw from fewer than two counts.
 */
export function memberTrend(
  snapshots: MemberSnapshot[],
): { points: string; first: number; last: number; change: number } | null {
  if (snapshots.length < 2) return null;
  const counts = snapshots.map((snapshot) => snapshot.member_count);
  const low = Math.min(...counts);
  const high = Math.max(...counts);
  const step = 100 / (counts.length - 1);
  const y = (count: number) =>
    high === low ? 16 : 32 - ((count - low) / (high - low)) * 32;
  const round = (n: number) => Math.round(n * 10) / 10;
  const points = counts
    .map((count, i) => `${round(i * step)},${round(y(count))}`)
    .join(' ');
  const first = counts[0] ?? 0;
  const last = counts.at(-1) ?? 0;
  return { points, first, last, change: last - first };
}

/**
 * The chats this one may go under. The console's list groups one level deep,
 * so only a top-level chat is offered, and a chat others already sit under
 * stays at the top itself.
 */
export function parentChoices(chats: ConsoleChat[], chatId: number): ConsoleChat[] {
  if (chats.some((chat) => chat.parent_chat_id === chatId)) return [];
  return chats
    .filter((chat) => chat.id !== chatId && chat.parent_chat_id === null)
    .sort((a, b) => (a.title ?? '').localeCompare(b.title ?? ''));
}
