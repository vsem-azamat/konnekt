/**
 * The console's Audience screens, apart from the screens: webapi's shapes for
 * the list and one person. The trends are in trends.ts.
 */

export type AudienceStatus = 'reachable' | 'never_started' | 'blocked' | 'opted_out';
export type Touchpoint = 'main_bot' | 'contact_bot' | 'mini_app' | 'moved_bot';

/** About the main bot, the one an announcement would come from. They do not overlap. */
export const STATUSES: AudienceStatus[] = [
  'reachable',
  'never_started',
  'blocked',
  'opted_out',
];
export const TOUCHPOINTS: Touchpoint[] = [
  'main_bot',
  'mini_app',
  'contact_bot',
  'moved_bot',
];

export const PAGE_SIZE = 50;

/** The source the backfill gives a private contact it could only estimate; see app/audience/backfill.py. */
export const ESTIMATE_SOURCE = 'backfill:dm_estimate';

/** The audience on the Overview; see app/audience/trends.py's overview. */
export interface AudienceOverview {
  /** Gave the main bot leave to write or opened the Mini App: the Audience page's «пришли к нам». */
  came: {
    total: number;
    /** The last seven whole days and the seven before; null where not wholly recorded. */
    now: number | null;
    before: number | null;
    /** The first day a week can be compared with the one before, YYYY-MM-DD. */
    compare_from: string;
  };
  main_bot: { reachable: number; blocked: number; opted_out: number };
  /** Everyone who wrote to the contact bot, which is also the ads desk. */
  contact_bot: { wrote: number; blocked: number; ads_conversations: number };
  /** People who reached us through a retired bot. */
  moved_bot: number;
}

export interface AudienceMember {
  user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  language_code: string | null;
  first_seen_at: string;
  last_seen_at: string;
  status: AudienceStatus;
  touchpoints: Touchpoint[];
}

export interface AudiencePage {
  total: number;
  items: AudienceMember[];
  /** The cursor for the next page; null on the last. */
  next: string | null;
}

export interface AudienceReach {
  bot: string;
  started_at: string | null;
  blocked_at: string | null;
}

export interface AudiencePerson extends AudienceMember {
  is_premium: boolean;
  source: string | null;
  opted_out_at: string | null;
  touches: { touchpoint: Touchpoint; first_at: string; last_at: string; count: number }[];
  reach: AudienceReach[];
}

export interface AudienceFilters {
  touchpoint?: Touchpoint;
  status?: AudienceStatus;
  q?: string;
  /** Only people first seen within this many days: the summary's window. */
  new_days?: number;
}

export function audiencePath(filters: AudienceFilters, cursor: string | null): string {
  const params = new URLSearchParams();
  if (filters.touchpoint) params.set('touchpoint', filters.touchpoint);
  if (filters.status) params.set('status', filters.status);
  const q = filters.q?.trim();
  if (q) params.set('q', q);
  if (filters.new_days) params.set('new_days', String(filters.new_days));
  params.set('limit', String(PAGE_SIZE));
  if (cursor) params.set('cursor', cursor);
  return `/api/audience?${params.toString()}`;
}

/** Whether `bot` may write: opened and not blocked since, blocked, or never opened. */
export function reachOf(
  reach: AudienceReach[],
  bot: string,
): 'open' | 'blocked' | 'never' {
  const row = reach.find((r) => r.bot === bot);
  if (!row) return 'never';
  if (row.blocked_at) return 'blocked';
  return row.started_at ? 'open' : 'never';
}
