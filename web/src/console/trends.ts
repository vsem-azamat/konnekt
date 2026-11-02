/**
 * The audience over time: webapi's shape for the trends (app/audience/trends.py)
 * and the arithmetic the screen does on it. A bar the server has no record for
 * is null, not 0: "nobody came" and "we did not count yet" must not look the same.
 */

export type Period = 7 | 30 | 90;
export const PERIODS: Period[] = [7, 30, 90];

export type Metric = 'starts' | 'app_new' | 'joins' | 'blocks';
export const METRICS: Metric[] = ['starts', 'app_new', 'joins', 'blocks'];

/** Whether more of it is good news; only those may be shown in green. */
export const GOOD_WHEN_UP: Record<Metric, boolean> = {
  starts: true,
  app_new: true,
  joins: true,
  blocks: false,
};

/**
 * One bar: a day up to a month, a week past that, where 90 thin bars would
 * be unreadable on a phone.
 */
export interface TrendPoint {
  /** The first and last UTC date the bar covers, YYYY-MM-DD. */
  from: string;
  to: string;
  starts: number | null;
  app_new: number | null;
  joins: number | null;
  blocks: number | null;
}

export interface Funnel {
  /** Wrote in a chat in the last 180 days, asked to join one, or is a member the bot knows of. */
  seen_in_chats: number;
  /** Pressed Start in the main bot at least once. */
  started_bot: number;
  /** Opened the Mini App at least once. */
  opened_app: number;
  /** Did both. */
  both: number;
  /** Of those who came to the bot or the Mini App, how many the bot never saw in a chat. */
  not_from_chats: number;
  /** The main bot may write to them now: started it and have not blocked it. */
  reachable: number;
  blocked: number;
  opted_out: number;
  /** Guessed by the backfill to have written to the bot; never confirmed. */
  estimate: number;
}

export interface Segment {
  key: string;
  /** A chat's title; for the folded rest, how many rows it holds. */
  label: string;
  /** People who came to the bot or the Mini App. */
  people: number;
}

export interface AudienceTrends {
  days: Period;
  today: string;
  /** The first day each metric was recorded; bars before it are null. */
  counted_since: Record<Metric, string>;
  /** Bars for the period before, then this period, oldest first, as many of each; the last ends yesterday. */
  series: TrendPoint[];
  /** Today so far: half a day beside whole ones would read as a fall, so it is apart. */
  today_point: TrendPoint;
  /** Each period's sum; null when none of it was recorded. */
  totals: Record<Metric, { now: number | null; before: number | null }>;
  funnel: Funnel;
  /** Gained since this period began. */
  funnel_new: Pick<Funnel, 'started_bot' | 'opened_app'>;
  segments: { chats: Segment[]; languages: Segment[]; sources: Segment[] };
}

/** This period's bars and the period's before it, apart. */
export function splitPeriods(trends: AudienceTrends): {
  now: TrendPoint[];
  before: TrendPoint[];
} {
  const half = trends.series.length / 2;
  return { now: trends.series.slice(half), before: trends.series.slice(0, half) };
}

/** One bar of one metric, as the charts draw it. */
export interface Bar {
  from: string;
  to: string;
  value: number | null;
}

/** One metric's bars out of the series. */
export function barsOf(points: TrendPoint[], metric: Metric): Bar[] {
  return points.map((p) => ({ from: p.from, to: p.to, value: p[metric] }));
}

/** Change against the period before, or null when either side was not counted. */
export function change(
  now: number | null,
  before: number | null,
): { diff: number; share: number | null } | null {
  if (now === null || before === null) return null;
  return { diff: now - before, share: before === 0 ? null : (now - before) / before };
}

/**
 * The first day a metric can be compared with a whole period before it:
 * two periods after its record began.
 */
export function comparableFrom(since: string, days: Period): string {
  // Past a month a bar is a week, so a period is whole weeks.
  const length = days > 30 ? Math.ceil(days / 7) * 7 : days;
  const date = new Date(`${since}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + length * 2);
  return date.toISOString().slice(0, 10);
}

/** The people who came to us, apart by how: the bot only, both, the Mini App only. */
export function overlap(funnel: Funnel): {
  botOnly: number;
  both: number;
  appOnly: number;
  total: number;
} {
  const botOnly = funnel.started_bot - funnel.both;
  const appOnly = funnel.opened_app - funnel.both;
  return { botOnly, both: funnel.both, appOnly, total: botOnly + funnel.both + appOnly };
}

/** A share as a whole percent, or with one decimal below ten: «3,6%». */
export function percent(part: number, whole: number, locale: string): string {
  if (whole <= 0) return '—';
  const share = (part / whole) * 100;
  return `${share.toLocaleString(locale, { maximumFractionDigits: share < 10 ? 1 : 0 })}%`;
}
