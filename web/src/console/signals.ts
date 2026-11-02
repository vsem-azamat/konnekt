import type { AdminCounts } from '../lib/generated/types.gen.ts';
import { ConsoleError, utc } from './session.ts';

/**
 * What waits for an admin, as webapi's `/api/signals` tells it, and the
 * counters the browser's menu shows from it.
 */

/** A burst of join requests to one chat that nobody decided yet. */
export interface WaveSignal {
  id: number;
  chat_id: number;
  chat_title: string | null;
  member_count: number | null;
  started_at: string;
  last_surge_at: string;
  held: number;
  paused: boolean;
  /** When the pause ends unless another burst comes first. */
  quiet_until: string;
}

export interface Signals {
  waves: WaveSignal[];
  /** People asking to join one chat within a minute that make a wave. */
  wave_per_minute: number;
  /** How many wait, and when the oldest of them came in; null when none does. */
  queues: {
    ads_unreviewed: number;
    ads_waiting_since: string | null;
    chats_in_review: number;
    chats_waiting_since: string | null;
  };
}

export interface MenuCounts {
  signals: number;
  chats: number;
  spam: number;
  catalog: number;
}

/**
 * How many wait behind each menu item. Unknown is zero: the menu shows no
 * badge rather than a guess while an answer is missing.
 */
export function menuCounts(
  signals: Signals | undefined,
  catalog: { profiles_to_review: number } | undefined,
): MenuCounts {
  return {
    signals: signals?.waves.length ?? 0,
    chats: signals?.queues.chats_in_review ?? 0,
    spam: signals?.queues.ads_unreviewed ?? 0,
    catalog: catalog?.profiles_to_review ?? 0,
  };
}

export type QueueKey = 'ads' | 'review' | 'profiles' | 'requests';

/** One of the console's queues: how many wait, and since when the oldest. */
export interface Queue {
  key: QueueKey;
  count: number;
  since: string | null;
}

/**
 * The queues with something in them, in the order the console lists them:
 * webapi's two, then the catalog's. An answer still missing adds none.
 */
export function queues(
  signals: Signals | undefined,
  catalog:
    | Pick<
        AdminCounts,
        | 'profiles_to_review'
        | 'profiles_waiting_since'
        | 'unanswered'
        | 'unanswered_waiting_since'
      >
    | undefined,
): Queue[] {
  const all: Queue[] = [];
  if (signals) {
    all.push(
      {
        key: 'ads',
        count: signals.queues.ads_unreviewed,
        since: signals.queues.ads_waiting_since,
      },
      {
        key: 'review',
        count: signals.queues.chats_in_review,
        since: signals.queues.chats_waiting_since,
      },
    );
  }
  if (catalog) {
    all.push(
      {
        key: 'profiles',
        count: catalog.profiles_to_review,
        since: catalog.profiles_waiting_since,
      },
      {
        key: 'requests',
        count: catalog.unanswered,
        since: catalog.unanswered_waiting_since,
      },
    );
  }
  return all.filter((queue) => queue.count > 0);
}

/** Under this a wait reads in hours: «1 день» for 47 hours hides most of a day. */
const HOURS_BEFORE_DAYS = 48;

/** How long the oldest in a queue waits: under an hour, in hours, then in days. */
export function waited(
  iso: string,
  now: Date = new Date(),
): { unit: 'fresh' } | { unit: 'hours' | 'days'; count: number } {
  const hours = Math.floor(minutesSince(iso, now) / 60);
  if (hours === 0) return { unit: 'fresh' };
  if (hours < HOURS_BEFORE_DAYS) return { unit: 'hours', count: hours };
  return { unit: 'days', count: Math.floor(hours / 24) };
}

/** Whole minutes from a webapi time to now; a time in the future is zero. */
export function minutesSince(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(utc(iso)).getTime()) / 60_000));
}

/** Minutes left until a webapi time, a started one counted whole; past is zero. */
export function minutesUntil(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.ceil((new Date(utc(iso)).getTime() - now.getTime()) / 60_000));
}

/** How long ago, as the screen says it: just now, in minutes, then in hours. */
export function elapsed(
  iso: string,
  now: Date = new Date(),
): { unit: 'now' } | { unit: 'minutes' | 'hours'; count: number } {
  const minutes = minutesSince(iso, now);
  if (minutes === 0) return { unit: 'now' };
  if (minutes < 60) return { unit: 'minutes', count: minutes };
  return { unit: 'hours', count: Math.floor(minutes / 60) };
}

/** Why a press on the Сигналы screen did not go through. */
export type DecisionProblem = 'gone' | 'decided' | 'failed';

/** webapi's refusal of a decision, as the card should explain it. */
export function decisionProblem(error: unknown): DecisionProblem {
  if (!(error instanceof ConsoleError)) return 'failed';
  if (error.status === 404) return 'gone';
  if (error.detail === 'decided otherwise') return 'decided';
  return 'failed';
}
