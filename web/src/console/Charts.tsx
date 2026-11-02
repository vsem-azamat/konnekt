import { Trans, useLingui } from '@lingui/react/macro';

import { Hint, ui } from '@/components/Ui';
import { localHeatmap, memberTrend } from '@/console/activity';
import { type HeatmapCell, type MemberSnapshot, utc } from '@/console/session';

/**
 * When the chat talks: a week of messages by weekday and hour, in the
 * reader's time. Darker is busier; the scale is this chat's own busiest hour.
 */
export function Heatmap({ cells }: { cells: HeatmapCell[] }) {
  const { t } = useLingui();
  const { grid, max } = localHeatmap(cells, -new Date().getTimezoneOffset());
  if (max === 0) {
    return (
      <Hint>
        <Trans>За неделю бот не видел здесь сообщений.</Trans>
      </Hint>
    );
  }
  const days = [t`Пн`, t`Вт`, t`Ср`, t`Чт`, t`Пт`, t`Сб`, t`Вс`];
  const peakDay = grid.findIndex((hours) => hours.includes(max));
  const peakHour = grid[peakDay]?.indexOf(max) ?? 0;
  const busiest = `${days[peakDay]}, ${String(peakHour).padStart(2, '0')}:00`;
  return (
    <div
      className={ui.heatmap}
      role="img"
      aria-label={t`Сообщения по дням недели и часам; больше всего: ${busiest}`}
    >
      {grid.map((hours, day) => (
        <div key={days[day]} className={ui.heatmapRow}>
          <span className={ui.heatmapDay}>{days[day]}</span>
          {hours.map((count, hour) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: the hour is the identity.
              key={hour}
              className={ui.heatmapCell}
              style={{ opacity: count ? 0.18 + 0.82 * (count / max) : 1 }}
              data-empty={count === 0 || undefined}
            />
          ))}
        </div>
      ))}
      <div className={ui.heatmapRow}>
        <span className={ui.heatmapDay} />
        {[0, 6, 12, 18].map((hour) => (
          <span
            key={hour}
            className={ui.heatmapHour}
            style={{ gridColumn: `${hour + 2} / span 6` }}
          >
            {hour}
          </span>
        ))}
      </div>
    </div>
  );
}

/** How the member count moved over the counts the bot took. */
export function MemberTrend({ snapshots }: { snapshots: MemberSnapshot[] }) {
  const { i18n } = useLingui();
  const trend = memberTrend(snapshots.map((snapshot) => snapshot.member_count));
  if (!trend) {
    return (
      <Hint>
        <Trans>Участников посчитали меньше двух раз: линии пока нет.</Trans>
      </Hint>
    );
  }
  const since = i18n.date(utc(snapshots[0]?.captured_at ?? ''), {
    day: 'numeric',
    month: 'short',
  });
  const sign = trend.change > 0 ? '+' : trend.change < 0 ? '−' : '±';
  return (
    <div className={ui.trend}>
      {/* The facts beside it say what the line shows. */}
      <svg
        aria-hidden="true"
        viewBox="-1 -2 102 36"
        preserveAspectRatio="none"
        className={ui.trendLine}
      >
        <polyline points={trend.points} fill="none" vectorEffect="non-scaling-stroke" />
      </svg>
      <span className={ui.trendFacts}>
        <b>
          {sign}
          {i18n.number(Math.abs(trend.change))}
        </b>{' '}
        <Trans>
          с {since}: {i18n.number(trend.first)} → {i18n.number(trend.last)}
        </Trans>
      </span>
    </div>
  );
}
