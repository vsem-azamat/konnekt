/**
 * The console's «Использование» and «Источники», apart from the screens:
 * webapi's shapes (app/webapi/schemas.py, Usage and Sources) and the
 * arithmetic the screens do on them. The words are the screens' own.
 */

export type UsagePeriod = 1 | 7 | 30;
export const USAGE_PERIODS: UsagePeriod[] = [1, 7, 30];

export type SourcesPeriod = 7 | 30 | 90;
export const SOURCES_PERIODS: SourcesPeriod[] = [7, 30, 90];

export type FunnelKey = 'find' | 'offer' | 'chats';
export const FUNNELS: FunnelKey[] = ['find', 'chats', 'offer'];

export interface UsageDay {
  /** A day in Prague, YYYY-MM-DD. */
  day: string;
  sessions: number;
  people: number;
}

export interface UsageHour {
  /** Monday is 0, as Python counts. */
  weekday: number;
  hour: number;
  people: number;
}

export interface UsageLength {
  from_seconds: number;
  /** null is «and longer». */
  to_seconds: number | null;
  sessions: number;
}

export interface Usage {
  days: UsagePeriod;
  /** The first event ever written: before it nothing was counted. */
  since: string | null;
  online: number;
  people: number;
  sessions: number;
  median_seconds: number | null;
  by_day: UsageDay[];
  heat: UsageHour[];
  lengths: UsageLength[];
  screens: { screen: string; people: number }[];
  taps: { name: string; detail: string | null; count: number }[];
  funnels: { key: FunnelKey; steps: { key: string; people: number }[] }[];
  /** Launches by the start parameter Telegram signed; null is none. */
  entries: { source: string | null; launches: number }[];
}

export interface SourcesTop {
  key: string;
  visits: number;
}

export interface Sources {
  days: SourcesPeriod;
  site: {
    /** False: Cloudflare Web Analytics is not connected yet. */
    on: boolean;
    /** The last day imported, YYYY-MM-DD. */
    /** The first and last day imported, YYYY-MM-DD. */
    since: string | null;
    through: string | null;
    visits: number;
    views: number;
    by_day: { day: string; visits: number }[];
    referrers: SourcesTop[];
    pages: SourcesTop[];
  };
  search: {
    /** False: Search Console is not connected yet. */
    on: boolean;
    /** The first and last day imported, YYYY-MM-DD. */
    since: string | null;
    through: string | null;
    clicks: number;
    impressions: number;
    queries: { query: string; clicks: number; impressions: number; position: number }[];
  };
  to_app: {
    launches: number;
    by_source: { source: string; launches: number }[];
  };
}

/** The whole of a day, or no referrer, in the import (app/usage/sources.py). */
export const WHOLE = '*';

/** «2:40» for a session's length; past an hour «1:05:00». */
export function duration(seconds: number): string {
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`;
}

export interface HeatCell {
  weekday: number;
  hour: number;
  people: number;
  /** 0 is nobody; 1 to 4 split the busiest hour into quarters. */
  level: 0 | 1 | 2 | 3 | 4;
}

/**
 * Seven rows of 24 hours, Monday first, every hour present: the server
 * sends only hours somebody was in. A level is a quarter of the busiest
 * hour, so one person in a quiet week still shows.
 */
export function heatGrid(heat: UsageHour[]): HeatCell[][] {
  const top = Math.max(0, ...heat.map((h) => h.people));
  const people = new Map(heat.map((h) => [h.weekday * 24 + h.hour, h.people]));
  return Array.from({ length: 7 }, (_, weekday) =>
    Array.from({ length: 24 }, (_, hour) => {
      const n = people.get(weekday * 24 + hour) ?? 0;
      const level = n === 0 || top === 0 ? 0 : Math.max(1, Math.ceil((n / top) * 4));
      return { weekday, hour, people: n, level: level as HeatCell['level'] };
    }),
  );
}

/**
 * What a start parameter is, for the label: a site button (`site_hero`), an
 * article on the site (`site_article_<slug>`), a university's chat link
 * (`uni-cvut`), or one of the bot's own links as it is.
 */
export type SourceKind =
  | { kind: 'none' }
  | { kind: 'article'; slug: string }
  | { kind: 'site'; place: string }
  | { kind: 'university'; code: string }
  | { kind: 'link'; key: string };

export function sourceKind(source: string | null): SourceKind {
  if (!source) return { kind: 'none' };
  if (source.startsWith('site_article_')) {
    return { kind: 'article', slug: source.slice('site_article_'.length) };
  }
  if (source.startsWith('site_')) return { kind: 'site', place: source.slice(5) };
  if (source.startsWith('uni-')) return { kind: 'university', code: source.slice(4) };
  return { kind: 'link', key: source };
}

/** What a tap's detail says: the school a chat belongs to, or where the tap came from. */
export type TapDetail =
  | { kind: 'none' }
  | { kind: 'school'; code: string }
  | { kind: 'general' }
  | { kind: 'from'; key: string };

/** A chat tap carries its school's code, or `none` for a chat tied to no school (components/ChatRow.tsx). */
export function tapDetail(name: string, detail: string | null): TapDetail {
  if (!detail) return { kind: 'none' };
  if (name === 'chat_open') {
    return detail === 'none' ? { kind: 'general' } : { kind: 'school', code: detail };
  }
  return { kind: 'from', key: detail };
}

/** «В среднем 5,5 место»: one decimal, the reader's way. */
export function position(value: number, locale: string): string {
  return value.toLocaleString(locale, { maximumFractionDigits: 1 });
}

/** A share of `whole` as a whole percent, or null where there is nothing to share. */
export function shareOf(part: number, whole: number): number | null {
  return whole > 0 ? Math.round((part / whole) * 100) : null;
}
