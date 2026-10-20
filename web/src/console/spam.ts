/** The console's ads queue, apart from the screen. */

import { type SpamPing, utc } from './session.ts';

/** How many hits a page of the queue holds. */
export const PAGE = 50;

export type PingStatus = 'unreviewed' | 'all' | 'not_ad';

export interface PingFilters {
  status: PingStatus;
  chatId: number | null;
  /** The last this many days; none for as far back as the bot keeps. */
  days: number | null;
}

export function pingsPath(filters: PingFilters, beforeId?: number): string {
  const query = new URLSearchParams({ limit: String(PAGE), status: filters.status });
  if (filters.chatId !== null) query.set('chat_id', String(filters.chatId));
  if (filters.days !== null) query.set('days', String(filters.days));
  if (beforeId !== undefined) query.set('before_id', String(beforeId));
  return `/api/spam/pings?${query}`;
}

/** Where the next page starts; a short page was the last one. */
export function nextBefore(page: SpamPing[]): number | undefined {
  return page.length === PAGE ? page.at(-1)?.id : undefined;
}

/** A ban answers every hit of theirs, as webapi's queue counts it. */
export function awaitsAnswer(ping: SpamPing): boolean {
  return ping.verdict === null && !ping.blocked;
}

/**
 * Hits by the reader's own day, in the order given: «today», «yesterday»,
 * else the date as YYYY-MM-DD for the screen to write out.
 */
export function byDay(
  pings: SpamPing[],
  now: Date = new Date(),
): { day: string; pings: SpamPing[] }[] {
  const key = (date: Date) =>
    `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
  const today = key(now);
  const yesterday = key(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  const groups: { day: string; pings: SpamPing[] }[] = [];
  for (const ping of pings) {
    const date = key(new Date(utc(ping.detected_at)));
    const day = date === today ? 'today' : date === yesterday ? 'yesterday' : date;
    const last = groups.at(-1);
    if (last?.day === day) last.pings.push(ping);
    else groups.push({ day, pings: [ping] });
  }
  return groups;
}
