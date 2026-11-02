import { Trans, useLingui } from '@lingui/react/macro';
import { type ReactNode, useState } from 'react';

import css from '@/console/Audience.module.css';
import { type Bar, change, type Funnel, overlap } from '@/console/trends';

/** A UTC date as «3 ноя», in the reader's language. */
export function useDay(): (date: string) => string {
  const { i18n } = useLingui();
  const format = new Intl.DateTimeFormat(i18n.locale, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });
  return (date: string) => format.format(new Date(`${date}T00:00:00Z`));
}

function useSpan(): (point: Bar) => string {
  const day = useDay();
  return (point) =>
    point.from === point.to ? day(point.from) : `${day(point.from)} – ${day(point.to)}`;
}

/**
 * Bars for one metric, with the period before as a tick on each bar. A bar
 * not yet counted is hatched rather than empty: zero is an answer, and that
 * is not one. Today, unfinished, is an outline after the bars and in no
 * comparison. Touching or hovering a bar reads it out above the chart, which
 * a phone, with no hover, needs.
 */
export function TrendBars({
  now,
  before,
  today,
  unit,
  tall = false,
}: {
  now: Bar[];
  before?: Bar[];
  today?: Bar;
  /** What one bar counts, for the readout: «3 человека». */
  unit: (count: number) => ReactNode;
  tall?: boolean;
}) {
  const span = useSpan();
  const [picked, setPicked] = useState<number | null>(null);
  const values = [...now, ...(before ?? []), ...(today ? [today] : [])].map(
    (p) => p.value ?? 0,
  );
  const top = Math.max(1, ...values);
  // The last whole day is read out first: today's few hours say little.
  const shown = picked ?? now.length - 1;
  const onToday = today !== undefined && shown === now.length;
  const point = onToday ? today : now[shown];
  const first = now[0];
  const last = today ?? now[now.length - 1];
  if (!point || !first || !last) return null;
  const previous = onToday ? undefined : before?.[shown];

  return (
    <div className={css.trend}>
      <div className={css.readout} aria-live="polite">
        <span>{onToday ? <Trans>сегодня, день не закончился</Trans> : span(point)}</span>
        <b>{point.value === null ? <Trans>не считали</Trans> : unit(point.value)}</b>
        {previous && previous.value !== null ? (
          <span className={css.readoutBefore}>
            <Trans>период раньше: {previous.value}</Trans>
          </span>
        ) : null}
      </div>
      <div
        className={css.bars}
        data-tall={tall || undefined}
        onPointerLeave={() => setPicked(null)}
      >
        <span className={css.max} style={{ bottom: '100%' }} aria-hidden>
          {top}
        </span>
        {now.map((p, index) => {
          const old = before?.[index]?.value;
          return (
            <button
              key={p.from}
              type="button"
              className={css.bar}
              data-picked={index === shown || undefined}
              data-uncounted={p.value === null || undefined}
              aria-label={`${span(p)}: ${p.value ?? '—'}`}
              onPointerEnter={() => setPicked(index)}
              onFocus={() => setPicked(index)}
              onClick={() => setPicked(index)}
            >
              <span style={{ height: `${((p.value ?? top * 0.12) / top) * 100}%` }} />
              {old !== undefined && old !== null ? (
                <i style={{ bottom: `${(old / top) * 100}%` }} />
              ) : null}
            </button>
          );
        })}
        {today ? (
          <button
            type="button"
            className={css.bar}
            data-today
            data-picked={onToday || undefined}
            aria-label={`${span(today)}: ${today.value ?? '—'}`}
            onPointerEnter={() => setPicked(now.length)}
            onFocus={() => setPicked(now.length)}
            onClick={() => setPicked(now.length)}
          >
            <span style={{ height: `${((today.value ?? 0) / top) * 100}%` }} />
          </button>
        ) : null}
      </div>
      <div className={css.axis}>
        <span>{span(first).split(' – ')[0]}</span>
        <span>{span(last).split(' – ').pop()}</span>
      </div>
    </div>
  );
}

/** «+12 (+40%) к прошлому периоду», green only when more is good news. */
export function Delta({
  now,
  before,
  goodWhenUp,
  pending,
}: {
  now: number | null;
  before: number | null;
  goodWhenUp: boolean;
  /** Said instead while the period before was not wholly recorded. */
  pending: ReactNode;
}) {
  const delta = change(now, before);
  if (delta === null) return <span className={css.delta}>{pending}</span>;
  const sign = delta.diff > 0 ? '+' : delta.diff < 0 ? '−' : '±';
  const share =
    delta.share === null || Math.abs(delta.diff) < 5
      ? ''
      : ` (${sign}${Math.round(Math.abs(delta.share) * 100)}%)`;
  const good = delta.diff > 0 && goodWhenUp;
  return (
    <span className={css.delta} data-good={good || undefined}>
      {delta.diff > 0 ? '↑' : delta.diff < 0 ? '↓' : ''} {sign}
      {Math.abs(delta.diff)}
      {share} <Trans>к прошлому периоду</Trans>
    </span>
  );
}

/** A small line of one metric, for a tile. */
export function Spark({ points }: { points: Bar[] }) {
  const values = points.map((p) => p.value);
  const top = Math.max(1, ...values.map((v) => v ?? 0));
  const step = 100 / Math.max(1, points.length - 1);
  const path = values
    .map((v, i) => (v === null ? null : `${i * step},${30 - (v / top) * 28}`))
    .filter(Boolean)
    .join(' ');
  return (
    <svg
      className={css.spark}
      viewBox="0 0 100 32"
      preserveAspectRatio="none"
      aria-hidden
    >
      <polyline points={path} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export interface Step {
  key: string;
  title: ReactNode;
  /** Who is counted, in a sentence. */
  who: ReactNode;
  count: number;
  /** Its share of the step before, beside the count: on one scale a small step is a sliver. */
  share?: ReactNode;
}

/**
 * The way from a chat to us, each step with who it counts. The bars
 * share one scale, the first step's, so a step is as long as its share of it.
 */
export function FunnelSteps({
  steps,
  extra,
}: {
  steps: Step[];
  extra?: Record<string, ReactNode>;
}) {
  const base = Math.max(1, steps[0]?.count ?? 1);
  return (
    <ol className={css.funnel}>
      {steps.map((step) => (
        <li key={step.key}>
          <div className={css.stepHead}>
            <span className={css.stepTitle}>{step.title}</span>
            <span className={css.stepCount}>
              {step.share ? <span>{step.share}</span> : null}
              <b>{step.count}</b>
            </span>
          </div>
          <div className={css.stepTrack}>
            <span
              className={css.stepFill}
              style={{ width: `${Math.max(0.6, (step.count / base) * 100)}%` }}
            />
          </div>
          <div className={css.stepWho}>{step.who}</div>
          {extra?.[step.key] ?? null}
        </li>
      ))}
    </ol>
  );
}

/** Who came: the bot may write and no Mini App, the Mini App and the bot may write, the Mini App alone. */
export function Overlap({ funnel }: { funnel: Funnel }) {
  const { t } = useLingui();
  const parts = overlap(funnel);
  const rows = [
    {
      key: 'bot',
      count: parts.botOnly,
      label: t`бот может писать, Mini App не открывали`,
    },
    { key: 'both', count: parts.both, label: t`Mini App, бот может писать` },
    { key: 'app', count: parts.appOnly, label: t`Mini App, писать боту не разрешили` },
  ];
  return (
    <div className={css.overlap}>
      <div
        className={css.overlapBar}
        role="img"
        aria-label={rows.map((r) => `${r.label}: ${r.count}`).join(', ')}
      >
        {rows.map((r) =>
          r.count > 0 ? (
            <span key={r.key} data-part={r.key} style={{ flex: r.count }} />
          ) : null,
        )}
      </div>
      <div className={css.overlapLegend}>
        {rows.map((r) => (
          <span key={r.key} data-part={r.key}>
            <b>{r.count}</b> {r.label}
          </span>
        ))}
      </div>
    </div>
  );
}

/** A segment list: largest first, each against the largest. */
export function SegmentBars({
  rows,
}: {
  rows: { key: string; label: string; people: number }[];
}) {
  const top = Math.max(1, ...rows.map((r) => r.people));
  if (rows.length === 0) {
    return (
      <p className={css.empty}>
        <Trans>Пока никого.</Trans>
      </p>
    );
  }
  return (
    <div className={css.segments}>
      {rows.map((r) => (
        <div key={r.key} className={css.segment}>
          <span>{r.label}</span>
          <span className={css.segmentTrack}>
            <span
              className={css.segmentFill}
              style={{ width: `${(r.people / top) * 100}%` }}
            />
          </span>
          <b>{r.people}</b>
        </div>
      ))}
    </div>
  );
}
