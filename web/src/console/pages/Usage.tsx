import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { type ReactNode, useState } from 'react';

import { Label, Segmented, SkeletonRows, Sub, Title } from '@/components/Ui';
import audience from '@/console/Audience.module.css';
import { FunnelSteps, SegmentBars, TrendBars, useDay } from '@/console/AudienceCharts';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { usageQuery } from '@/console/queries';
import css from '@/console/Usage.module.css';
import { useUsageLabels } from '@/console/UsageLabels';
import {
  duration,
  FUNNELS,
  type FunnelKey,
  heatGrid,
  shareOf,
  USAGE_PERIODS,
  type Usage,
  type UsagePeriod,
} from '@/console/usage';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * How the Mini App is used: who is in it now, when people come, how long
 * they stay, which screens they open and what they press, and how far they
 * get. Counted from what the app reports (app/usage/report.py); nothing
 * here names a person.
 */
export default function ConsoleUsagePage() {
  return (
    <ConsoleGate wide>
      <Title>
        <Trans>Использование</Trans>
      </Title>
      <UsageView />
    </ConsoleGate>
  );
}

function UsageView() {
  const [days, setDays] = useState<UsagePeriod>(7);
  const { data, isPending, error, refetch } = useQuery({
    ...usageQuery(days),
    placeholderData: keepPreviousData,
  });
  if (isPending) {
    return (
      <div style={{ marginTop: 16 }}>
        <SkeletonRows count={5} />
      </div>
    );
  }
  if (error || !data) {
    return (
      <div style={{ marginTop: 16 }}>
        <ConsoleFailure error={error} retry={() => void refetch()} />
      </div>
    );
  }
  return <Report data={data} days={days} setDays={setDays} />;
}

function sessions(count: number) {
  return (
    <Plural
      value={count}
      one="# сессия"
      few="# сессии"
      many="# сессий"
      other="# сессии"
    />
  );
}

function people(count: number) {
  return (
    <Plural
      value={count}
      one="# человек"
      few="# человека"
      many="# человек"
      other="# человека"
    />
  );
}

function Report({
  data,
  days,
  setDays,
}: {
  data: Usage;
  days: UsagePeriod;
  setDays: (days: UsagePeriod) => void;
}) {
  const { t } = useLingui();
  const day = useDay();
  const since = data.since ? day(data.since.slice(0, 10)) : null;
  const labels = {
    1: t`24 часа`,
    7: t`7 дней`,
    30: t`30 дней`,
  } satisfies Record<UsagePeriod, string>;

  return (
    <div>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>
            Что делают в Mini App. Время по вашему часовому поясу, сегодняшний день входит
            в период.
          </Trans>
        </Sub>
      </div>
      <div className={audience.period}>
        <Segmented
          value={String(days)}
          label={t`Период`}
          options={USAGE_PERIODS.map((p) => ({ value: String(p), label: labels[p] }))}
          onChange={(value) => {
            hapticSelection();
            setDays(Number(value) as UsagePeriod);
          }}
        />
        {since ? (
          <span>
            <Trans>считаем с {since}</Trans>
          </span>
        ) : null}
      </div>
      {data.since === null ? (
        <p className={css.notice}>
          <Trans>
            <b>Событий пока нет.</b> Счёт начнётся, когда выйдет версия Mini App, которая
            их отправляет, и в неё кто-нибудь зайдёт. Кто выключил учёт в профиле, сюда не
            попадает.
          </Trans>
        </p>
      ) : (
        <>
          <Tiles data={data} />
          <div className={css.grid}>
            <div className={`${audience.card} ${css.wide}`}>
              <Label aside={<Trans>человек в час</Trans>}>
                <Trans>Когда онлайн</Trans>
              </Label>
              <p className={audience.who}>
                <Trans>
                  Сколько разных людей было в приложении в каждый час недели за период.
                </Trans>
              </p>
              <Heat data={data} />
            </div>
            {data.by_day.length > 2 ? <Days data={data} /> : null}
            <Funnels data={data} />
            {/* In pairs, so no card stands alone in a row beside empty space. */}
            <div className={audience.card}>
              <Label aside={<Trans>сессий</Trans>}>
                <Trans>Сколько длится сессия</Trans>
              </Label>
              <p className={audience.who}>
                <Trans>
                  Сессия — пока приложение на экране; перерыв больше двух минут начинает
                  новую.
                </Trans>
              </p>
              <Lengths data={data} />
            </div>
            <Screens data={data} />
            <Taps data={data} />
            <Entries data={data} />
          </div>
        </>
      )}
    </div>
  );
}

function Tiles({ data }: { data: Usage }) {
  return (
    <div className={css.tiles}>
      <Tile
        label={<Trans>сейчас в приложении</Trans>}
        value={
          <>
            <span className={css.live} aria-hidden />
            {data.online}
          </>
        }
        hint={<Trans>за последнюю минуту</Trans>}
      />
      <Tile
        label={<Trans>человек</Trans>}
        value={data.people}
        hint={<Trans>заходили за период</Trans>}
      />
      <Tile
        label={<Trans>сессий</Trans>}
        value={data.sessions}
        hint={<Trans>заходов в приложение</Trans>}
      />
      <Tile
        label={<Trans>медиана сессии</Trans>}
        value={data.median_seconds === null ? '—' : duration(data.median_seconds)}
        hint={<Trans>минуты : секунды</Trans>}
      />
    </div>
  );
}

function Tile({
  label,
  value,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  hint: ReactNode;
}) {
  // A count in the language's grouping: «1 930», as the rest of the console writes it.
  const { i18n } = useLingui();
  return (
    <div className={css.tile}>
      <span>{label}</span>
      <span className={audience.big}>
        {typeof value === 'number' ? i18n.number(value) : value}
      </span>
      <span className={css.tileHint}>{hint}</span>
    </div>
  );
}

function Heat({ data }: { data: Usage }) {
  const { t } = useLingui();
  const days = [t`Пн`, t`Вт`, t`Ср`, t`Чт`, t`Пт`, t`Сб`, t`Вс`];
  const grid = heatGrid(data.heat);
  const top = Math.max(0, ...data.heat.map((h) => h.people));
  return (
    <>
      <div className={css.heat} role="img" aria-label={t`Люди по часам недели`}>
        {grid.map((row, weekday) => [
          <span key={`d${days[weekday]}`}>{days[weekday]}</span>,
          ...row.map((cell) => (
            <span
              key={`${cell.weekday}-${cell.hour}`}
              className={css.cell}
              data-level={cell.level}
              title={`${days[weekday]}, ${cell.hour}:00 — ${cell.people}`}
            />
          )),
        ])}
        <div className={css.hours} aria-hidden>
          <span>0</span>
          <span>6</span>
          <span>12</span>
          <span>18</span>
          <span>23</span>
        </div>
      </div>
      <div className={css.legend}>
        <span className={css.cell} data-level={0} />
        <Trans>никого</Trans>
        <span className={css.cell} data-level={1} />
        <span className={css.cell} data-level={2} />
        <span className={css.cell} data-level={3} />
        <span className={css.cell} data-level={4} />
        <Trans>больше всего: {top} в час</Trans>
      </div>
    </>
  );
}

function Days({ data }: { data: Usage }) {
  const { t } = useLingui();
  const [what, setWhat] = useState<'sessions' | 'people'>('sessions');
  const points = data.by_day.map((d) => ({ from: d.day, to: d.day, value: d[what] }));
  const today = points.pop();
  return (
    <div className={`${audience.card} ${css.wide}`}>
      <Label>
        <Trans>По дням</Trans>
      </Label>
      <div className={css.toggle}>
        <Segmented
          value={what}
          label={t`Что считать`}
          options={[
            { value: 'sessions', label: t`Сессии` },
            { value: 'people', label: t`Люди` },
          ]}
          onChange={(value) => {
            hapticSelection();
            setWhat(value);
          }}
        />
      </div>
      <TrendBars
        key={`${data.days}-${what}`}
        now={points}
        today={today}
        unit={what === 'sessions' ? sessions : people}
      />
    </div>
  );
}

function Lengths({ data }: { data: Usage }) {
  const { t } = useLingui();
  const label = (from: number, to: number | null) => {
    const a = from < 60 ? t`${from} с` : t`${from / 60} мин`;
    if (to === null) return t`от ${a}`;
    const b = to < 60 ? t`${to} с` : t`${to / 60} мин`;
    return from === 0 ? t`до ${b}` : `${a} – ${b}`;
  };
  return (
    <SegmentBars
      rows={data.lengths.map((l) => ({
        key: String(l.from_seconds),
        label: label(l.from_seconds, l.to_seconds),
        people: l.sessions,
      }))}
    />
  );
}

function Screens({ data }: { data: Usage }) {
  const labels = useUsageLabels();
  return (
    <div className={audience.card}>
      <Label aside={<Trans>человек</Trans>}>
        <Trans>Экраны</Trans>
      </Label>
      <p className={audience.who}>
        <Trans>Сколько разных людей открыли экран.</Trans>
      </p>
      <SegmentBars
        rows={data.screens.map((s) => ({
          key: s.screen,
          label: labels.screen(s.screen),
          people: s.people,
        }))}
      />
    </div>
  );
}

function Taps({ data }: { data: Usage }) {
  const labels = useUsageLabels();
  return (
    <div className={audience.card}>
      <Label aside={<Trans>раз</Trans>}>
        <Trans>Нажатия</Trans>
      </Label>
      <p className={audience.who}>
        <Trans>Главные кнопки, сколько раз нажали.</Trans>
      </p>
      <SegmentBars
        rows={data.taps.map((tap) => ({
          key: `${tap.name}:${tap.detail ?? ''}`,
          label: labels.tap(tap.name, tap.detail),
          people: tap.count,
        }))}
      />
    </div>
  );
}

function Entries({ data }: { data: Usage }) {
  const labels = useUsageLabels();
  return (
    <div className={audience.card}>
      <Label aside={<Trans>запусков</Trans>}>
        <Trans>Откуда открыли приложение</Trans>
      </Label>
      <p className={audience.who}>
        <Trans>
          По метке ссылки, с которой запустили. Возврат после перерыва не считается.
        </Trans>
      </p>
      <SegmentBars
        rows={data.entries.map((e) => ({
          key: e.source ?? '',
          label: labels.source(e.source),
          people: e.launches,
        }))}
      />
    </div>
  );
}

function Funnels({ data }: { data: Usage }) {
  const { t } = useLingui();
  const labels = useUsageLabels();
  const [key, setKey] = useState<FunnelKey>('find');
  const funnel = data.funnels.find((f) => f.key === key);
  const steps = (funnel?.steps ?? []).map((step, index, all) => {
    const before = all[index - 1];
    const share = before ? shareOf(step.people, before.people) : null;
    return {
      key: step.key,
      title: labels.step(key, step.key),
      who: null,
      count: step.people,
      share: share === null ? undefined : <Trans>{share}% от шага выше</Trans>,
    };
  });
  return (
    <div className={`${audience.card} ${css.wide}`}>
      <Label aside={<Trans>человек</Trans>}>
        <Trans>Воронки</Trans>
      </Label>
      <div className={`${css.toggle} ${css.scrolls}`}>
        <Segmented
          value={key}
          label={t`Воронка`}
          options={FUNNELS.map((f) => ({ value: f, label: labels.funnel[f] }))}
          onChange={(value) => {
            hapticSelection();
            setKey(value);
          }}
        />
      </div>
      <p className={audience.who}>
        <Trans>Сколько людей прошли шаги по порядку за период.</Trans>
      </p>
      <FunnelSteps steps={steps} />
    </div>
  );
}
