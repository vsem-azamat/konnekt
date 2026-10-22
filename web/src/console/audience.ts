/**
 * The console's Audience screens, apart from the screens: webapi's shapes and
 * the arithmetic behind the summary's bars.
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

export interface AudienceSummary {
  total: number;
  reach: Record<AudienceStatus, number>;
  /** By the touchpoint each person used first. */
  first_touch: Record<string, number>;
  /** New people per seven days, oldest first, the last ending now. */
  new_by_week: number[];
  new_this_week: number;
  languages: { code: string; count: number }[];
  /** People who have written to the ads bot, which is also the contact bot. */
  ads_conversations: number;
  /** People who blocked the contact bot; the main bot's blocks are in reach. */
  contact_bot_blocked: number;
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

/** The statuses that have anyone in them, in the bar's order. */
export function reachSegments(
  reach: Record<AudienceStatus, number>,
): { status: AudienceStatus; count: number }[] {
  return STATUSES.map((status) => ({ status, count: reach[status] ?? 0 })).filter(
    (segment) => segment.count > 0,
  );
}

/** Rows for a bar list, largest first, each sized against the largest. */
export function bars(
  counts: Record<string, number>,
): { key: string; count: number; share: number }[] {
  const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const largest = Math.max(1, ...rows.map(([, count]) => count));
  return rows.map(([key, count]) => ({ key, count, share: count / largest }));
}

/** The first few languages, and how many people speak one of the rest. */
export function topLanguages(
  languages: { code: string; count: number }[],
  shown: number,
): { top: { code: string; count: number }[]; rest: number } {
  return {
    top: languages.slice(0, shown),
    rest: languages.slice(shown).reduce((sum, language) => sum + language.count, 0),
  };
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
