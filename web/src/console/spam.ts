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

/** The last hit of a page, which the next one goes on after. */
export interface PageCursor {
  at: string;
  id: number;
}

function filterQuery(filters: Pick<PingFilters, 'chatId' | 'days'>): URLSearchParams {
  const query = new URLSearchParams();
  if (filters.chatId !== null) query.set('chat_id', String(filters.chatId));
  if (filters.days !== null) query.set('days', String(filters.days));
  return query;
}

export function pingsPath(filters: PingFilters, before?: PageCursor): string {
  const query = new URLSearchParams({ limit: String(PAGE), status: filters.status });
  for (const [key, value] of filterQuery(filters)) query.set(key, value);
  if (before !== undefined) {
    query.set('before_at', before.at);
    query.set('before_id', String(before.id));
  }
  return `/api/spam/pings?${query}`;
}

/** How many wait under the same chat and period as the list. */
export function unreviewedPath(filters: PingFilters): string {
  return `/api/spam/pings/unreviewed?${filterQuery(filters)}`;
}

/** Where the next page starts; a short page was the last one. */
export function nextBefore(page: SpamPing[]): PageCursor | undefined {
  const last = page.at(-1);
  return page.length === PAGE && last ? { at: last.detected_at, id: last.id } : undefined;
}

/** Waiting until answered: in the console, or «ad» by a ban that took. */
export function awaitsAnswer(ping: SpamPing): boolean {
  return ping.verdict === null;
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
