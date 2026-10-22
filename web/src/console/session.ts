/**
 * The moderator console's plumbing, apart from the screens that draw it.
 *
 * The console reads two backends. The catalog's `/api/v1/admin/*` takes the
 * same initData as every other catalog call. This repository's webapi keeps a
 * session instead: a cookie opened by `POST /api/auth/webapp` with the signed
 * initData, for super admins only. `consoleRequester` opens that session when
 * a request meets its absence, once, and never retries a refusal.
 */

import type { Topic } from '../lib/chats.ts';

/**
 * Why a console request failed, which decides what the screen says:
 * - `refused`: signed in, and webapi said this account is not a super admin;
 * - `stale`: no initData, or one webapi no longer accepts (it takes an hour's
 *   worth); reopening the app gives a fresh one;
 * - `not-kept`: signed in, and the next request still had no session, so the
 *   cookie was not kept (Telegram Web's iframe, for one); signing in again
 *   would only add sessions;
 * - `failed`: anything else, which may pass on another try.
 */
export type ConsoleFailureReason = 'refused' | 'stale' | 'not-kept' | 'failed';

export class ConsoleError extends Error {
  readonly status: number;
  readonly reason: ConsoleFailureReason;
  /** webapi's own code for a refusal (`already_known`), when it gave one. */
  readonly detail: string | null;

  constructor(
    status: number,
    reason: ConsoleFailureReason = 'failed',
    detail: string | null = null,
  ) {
    super(`console request failed: ${status} (${reason})`);
    this.name = 'ConsoleError';
    this.status = status;
    this.reason = reason;
    this.detail = detail;
  }
}

/** The `detail` of a FastAPI refusal, when it is a plain code rather than a list. */
async function detailOf(response: Response): Promise<string | null> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    return typeof body.detail === 'string' ? body.detail : null;
  } catch {
    return null;
  }
}

/**
 * Whether trying again can change the answer: not for the reasons above, and
 * not for a request the server understood and refused (a 404, a 422).
 */
export function isFinal(error: unknown): boolean {
  if (!(error instanceof ConsoleError)) return false;
  return error.reason !== 'failed' || error.status < 500;
}

export type ConsoleGet = <T>(path: string, init?: RequestInit) => Promise<T>;

/**
 * A requester for webapi's session endpoints. The fetch and the initData are
 * passed in: `api.ts` builds the real one, the tests a scripted one.
 */
export function consoleRequester(
  fetcher: typeof fetch,
  initData: () => string | undefined,
): ConsoleGet {
  // Shared by whatever requests meet the missing session at the same time:
  // one sign-in, not one per screen tile.
  let signingIn: Promise<void> | null = null;
  // Once a session was opened and not kept, opening more cannot help.
  let notKept = false;

  const signIn = async () => {
    const raw = initData();
    if (!raw) throw new ConsoleError(401, 'stale');
    const response = await fetcher('/api/auth/webapp', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ init_data: raw }),
    });
    if (response.status === 401) throw new ConsoleError(401, 'stale');
    if (response.status === 403) throw new ConsoleError(403, 'refused');
    if (!response.ok) throw new ConsoleError(response.status);
  };

  const send = (path: string, init: RequestInit) =>
    fetcher(path, {
      ...init,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
      },
    });

  return async <T>(path: string, init: RequestInit = {}): Promise<T> => {
    let response = await send(path, init);
    if (response.status === 401) {
      if (notKept) throw new ConsoleError(401, 'not-kept');
      signingIn ??= signIn().finally(() => {
        signingIn = null;
      });
      await signingIn;
      response = await send(path, init);
      if (response.status === 401) {
        notKept = true;
        throw new ConsoleError(401, 'not-kept');
      }
    }
    if (!response.ok) {
      throw new ConsoleError(response.status, 'failed', await detailOf(response));
    }
    return (response.status === 204 ? undefined : await response.json()) as T;
  };
}

// ── webapi's shapes, as far as the console reads them ─────────────────────

/**
 * How far the bot's hand reaches in a chat. Approved: it moderates. Observed:
 * it records and stays silent, since the owner's own bot is in charge.
 * External: it is not there; the chat is only listed, marked as not ours.
 */
export type ChatStatus = 'discovered' | 'approved' | 'observed' | 'external' | 'disabled';

export interface ConsoleChat {
  id: number;
  title: string | null;
  resource_status: ChatStatus;
  member_count: number | null;
  public_link: string | null;
  parent_chat_id: number | null;
  /** The university in the catalog's taxonomy, set on a chat at the top. */
  institution_code: string | null;
  /** As the taxonomy spells it («Praha»); null is all of Czechia, or the parent's. */
  city: string | null;
  /** The catalogue's heading; null is a university's chat, or one not filed yet. */
  topic: Topic | null;
  is_captcha_enabled: boolean;
  is_welcome_enabled: boolean;
  is_service_cleanup_enabled: boolean;
}

export interface ChatSender {
  user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  message_count: number;
  last_seen: string;
  blocked: boolean;
}

export interface BlockedUser {
  user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  /** When webapi's row last changed; a rename changes it too. */
  changed_at: string;
}

export interface AdminSession {
  id: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  user_agent: string | null;
  ip: string | null;
  is_current: boolean;
}

export interface SystemStatus {
  super_admin_ids: number[];
  publish_bot_ready: boolean;
  session_ttl_days: number;
  feature_flags: { name: string; enabled: boolean; source: string }[];
}

export interface HeatmapCell {
  /** 0 is Monday, in UTC. */
  weekday: number;
  /** 0–23, UTC. */
  hour: number;
  count: number;
}

export interface MemberSnapshot {
  captured_at: string;
  member_count: number;
}

/** One ad-detector hit, with the author as the bot last saw them. */
export interface SpamPing {
  id: number;
  chat_id: number;
  chat_title: string | null;
  user_id: number;
  username: string | null;
  first_name: string | null;
  last_name: string | null;
  blocked: boolean;
  message_id: number;
  kind: 'link' | 'mention' | string;
  matches: string[];
  snippet: string | null;
  detected_at: string;
  /** A moderator's answer; none while it waits in the queue. */
  verdict: SpamVerdict | null;
}

/** «ad» is written by a ban, the other two in the console. */
export type SpamVerdict = 'done' | 'not_ad' | 'ad';

export interface ConsoleChatDetail extends ConsoleChat {
  welcome_message: string | null;
  recent_senders: ChatSender[];
  heatmap: HeatmapCell[];
  member_snapshots: MemberSnapshot[];
  spam_pings: SpamPing[];
  children: { id: number; title: string | null }[];
}

/** The fields the console changes on a chat; only the ones sent are applied. */
export type ChatUpdate = Partial<
  Pick<
    ConsoleChatDetail,
    | 'resource_status'
    | 'is_captcha_enabled'
    | 'is_welcome_enabled'
    | 'is_service_cleanup_enabled'
    | 'welcome_message'
    | 'parent_chat_id'
    | 'institution_code'
    | 'city'
    | 'topic'
  > & { public_link: string }
>;

/** One of the busiest chats of the last 24 hours, by UTC hour of day. */
export interface BusyChat {
  chat_id: number;
  title: string | null;
  total_messages: number;
  hours: number[];
}

/** How a chat's member count moved; none where no count is old enough. */
export interface MemberDelta {
  chat_id: number;
  title: string | null;
  current: number | null;
  delta_24h: number | null;
  delta_7d: number | null;
}

export interface HomeStats {
  chat_heatmap: BusyChat[];
  members_delta: MemberDelta[];
  spam_pings: { count_24h: number; count_7d: number; unreviewed: number };
}

// ── what the summary says ─────────────────────────────────────────────────

export type AttentionKey = 'ads' | 'review' | 'requests';

/** What needs a look, in the order the summary lists it; zero is not news. */
export function attention(input: {
  adsUnreviewed: number;
  chats: Pick<ConsoleChat, 'resource_status'>[];
  requestsUnanswered: number;
}): { key: AttentionKey; count: number }[] {
  const items: { key: AttentionKey; count: number }[] = [
    { key: 'ads', count: input.adsUnreviewed },
    {
      key: 'review',
      count: input.chats.filter((chat) => chat.resource_status === 'discovered').length,
    },
    { key: 'requests', count: input.requestsUnanswered },
  ];
  return items.filter((item) => item.count > 0);
}

/** Clicks per impression as a percentage, one decimal; nothing without views. */
export function clickRate(
  impressions: number,
  clicks: number,
  locale = 'ru',
): string | null {
  if (impressions <= 0) return null;
  const rate = (clicks / impressions) * 100;
  const number = new Intl.NumberFormat(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(rate);
  return `${number} %`;
}

/** Whole days between an ISO time and now; today is zero. */
export function daysSince(iso: string, now: Date = new Date()): number {
  return Math.max(0, Math.floor((now.getTime() - new Date(iso).getTime()) / 86_400_000));
}

/**
 * A webapi time as the browser should read it. Webapi writes UTC without a
 * zone, which a browser would take for local time and show hours off.
 */
export function utc(iso: string): string {
  return /(Z|[+-]\d{2}:?\d{2})$/.test(iso) ? iso : `${iso}Z`;
}

/** The name Telegram gave, else the handle, else the id. */
export function personName(person: {
  user_id: number;
  first_name: string | null;
  last_name: string | null;
  username: string | null;
}): string {
  const name = [person.first_name, person.last_name].filter(Boolean).join(' ');
  return name || (person.username ? `@${person.username}` : String(person.user_id));
}
