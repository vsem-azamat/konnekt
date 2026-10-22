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

/** A ban or blacklisting proposed through MCP, waiting for a press. */
export interface PendingActionSignal {
  id: number;
  action: 'ban' | 'blacklist';
  /** None for every chat. */
  chat_id: number | null;
  chat_title: string | null;
  target_user_id: number;
  target_username: string | null;
  target_name: string | null;
  reason: string | null;
  created_at: string;
  expires_at: string;
}

export interface Signals {
  waves: WaveSignal[];
  /** People asking to join one chat within a minute that make a wave. */
  wave_per_minute: number;
  pending_actions: PendingActionSignal[];
  queues: { ads_unreviewed: number; chats_in_review: number };
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
    signals: (signals?.waves.length ?? 0) + (signals?.pending_actions.length ?? 0),
    chats: signals?.queues.chats_in_review ?? 0,
    spam: signals?.queues.ads_unreviewed ?? 0,
    catalog: catalog?.profiles_to_review ?? 0,
  };
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
export type DecisionProblem =
  | 'gone'
  | 'decided'
  | 'protected'
  | 'unmanaged'
  | 'refused'
  | 'failed';

/** webapi's refusal of a decision, as the card should explain it. */
export function decisionProblem(error: unknown): DecisionProblem {
  if (!(error instanceof ConsoleError)) return 'failed';
  if (error.status === 404 || error.detail === 'gone') return 'gone';
  if (error.detail === 'decided otherwise') return 'decided';
  if (error.detail === 'protected') return 'protected';
  if (error.detail === 'unmanaged') return 'unmanaged';
  // Telegram said no, and the proposal was closed as failed: another press finds it gone.
  if (error.status === 502 && error.detail === 'failed') return 'refused';
  return 'failed';
}
