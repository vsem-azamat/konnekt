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
