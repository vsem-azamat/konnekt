import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { type ReactNode, useState } from 'react';
import { useNavigate } from 'react-router';

import { PersonIcon } from '@/components/icons';
import {
  Chevron,
  Label,
  Row,
  Rows,
  Segmented,
  SkeletonRows,
  Sub,
  Tile,
  Title,
} from '@/components/Ui';
import css from '@/console/Audience.module.css';
import {
  Delta,
  FunnelSteps,
  Overlap,
  SegmentBars,
  Spark,
  type Step,
  TrendBars,
  useDay,
} from '@/console/AudienceCharts';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { audienceTrendsQuery } from '@/console/queries';
import {
  type AudienceTrends,
  barsOf,
  comparableFrom,
  GOOD_WHEN_UP,
  METRICS,
  type Metric,
  PERIODS,
  type Period,
  percent,
  periodLength,
  REST,
  type Segment,
  splitPeriods,
} from '@/console/trends';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * Who has used our bots or the Mini App, and how that changes: four trends
 * against the period before, then the way from a chat to us and where people
 * came from. Every number says who it counts. The list of people is a level
 * down. Nothing here sends anything.
 */
export default function ConsoleAudiencePage() {
  return (
    <ConsoleGate wide>
      <Title>
        <Trans>Аудитория</Trans>
      </Title>
      <AudienceView />
    </ConsoleGate>
  );
}

function AudienceView() {
  const [days, setDays] = useState<Period>(30);
  // Kept here, not in the view: switching the period must not reset the chart.
  const [picked, setPicked] = useState<Metric>('starts');
  const { data, isPending, error, refetch } = useQuery({
    ...audienceTrendsQuery(days),
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
  return (
    <Trends
      data={data}
      days={days}
      setDays={setDays}
      picked={picked}
      setPicked={setPicked}
    />
  );
}

/** What each metric is called and who it counts. */
function useMetrics(): Record<Metric, { title: string; who: ReactNode }> {
  const { t } = useLingui();
  return {
    starts: {
      title: t`Разрешили боту писать`,
      who: (
        <Trans>
          Впервые дали основному боту писать им: нажали Start, написали ему или разрешили
          в Mini App. Каждый считается один раз. Записываем с 20 окт.: кто пользовался
          ботом раньше, засчитан в день первого визита после этой даты.
        </Trans>
      ),
    },
    app_new: {
      title: t`Новые в Mini App`,
      who: (
        <Trans>
          Впервые открыли Mini App. Кто заходит снова, второй раз не считается.
        </Trans>
      ),
    },
    joins: {
      title: t`Бот впустил в чаты`,
      who: (
        <Trans>
          Заявки на вход в чаты, где вход проверяет бот, которые он одобрил: прошли капчу,
          недавно проходили её в другом чате или пришли из каталога. Два чата — два входа.
        </Trans>
      ),
    },
    blocks: {
      title: t`Заблокировали бота`,
      who: (
        <Trans>
          Заблокировали основной бот в этот день. Кто потом разблокировал, всё равно
          здесь.
        </Trans>
      ),
    },
  };
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

interface TrendsProps {
  data: AudienceTrends;
  days: Period;
  setDays: (days: Period) => void;
  picked: Metric;
  setPicked: (metric: Metric) => void;
}

/** Whether the whole period before was recorded, so that comparing with it means something. */
function comparable(data: AudienceTrends, metric: Metric): boolean {
  const first = data.series[0];
  return first !== undefined && first.from >= data.counted_since[metric];
}

function Trends({ data, days, setDays, picked, setPicked }: TrendsProps) {
  const { t } = useLingui();
  const day = useDay();
  const metrics = useMetrics();
  const { now, before } = splitPeriods(data);
  // Past a month a bar is a week, so 90 days are 13 weeks: say what is counted.
  const length = periodLength(data.days);

  const delta = (metric: Metric) => {
    const total = data.totals[metric];
    const from = day(comparableFrom(data.counted_since[metric], days));
    return (
      <Delta
        now={total.now}
        before={comparable(data, metric) ? total.before : null}
        goodWhenUp={GOOD_WHEN_UP[metric]}
        pending={<Trans>сравнение будет с {from}</Trans>}
      />
    );
  };

  return (
    <div className={css.page}>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>Как меняется аудитория и кого мы считаем.</Trans>
        </Sub>
      </div>
      <div className={css.period}>
        <Segmented
          value={String(days)}
          label={t`Период`}
          options={PERIODS.map((p) => ({ value: String(p), label: t`${p} дней` }))}
          onChange={(value) => {
            hapticSelection();
            setDays(Number(value) as Period);
          }}
        />
        <span>
          <Trans>
            {length} дней по вчера против {length} дней до них. Сегодня отдельно: день не
            закончился.
          </Trans>
        </span>
      </div>
      <div className={css.tiles}>
        {METRICS.map((metric) => {
          const total = data.totals[metric];
          const chosen = metric === picked;
          return (
            <button
              key={metric}
              type="button"
              className={css.tile}
              aria-pressed={chosen}
              onClick={() => {
                hapticSelection();
                setPicked(metric);
              }}
            >
              <span>{metrics[metric].title}</span>
              <span className={css.big}>{total.now ?? '—'}</span>
              {delta(metric)}
              <Spark points={barsOf(now, metric)} />
              <span className={css.tileHint}>
                {chosen ? <Trans>график ниже</Trans> : <Trans>показать график ↓</Trans>}
              </span>
            </button>
          );
        })}
      </div>
      <div className={css.card} style={{ marginTop: 12 }}>
        <div className={css.chartHead}>
          <h3>{metrics[picked].title}</h3>
          <span className={css.big}>{data.totals[picked].now ?? '—'}</span>
        </div>
        <div className={css.chartHead}>
          <span />
          {delta(picked)}
        </div>
        <p className={css.who}>{metrics[picked].who}</p>
        <TrendBars
          now={barsOf(now, picked)}
          before={comparable(data, picked) ? barsOf(before, picked) : undefined}
          today={barsOf([data.today_point], picked)[0]}
          unit={people}
          tall
        />
        <Counted data={data} metric={picked} />
      </div>
      <div className={css.grid}>
        <FunnelCard data={data} />
        <Segments data={data} />
      </div>
      <Links />
    </div>
  );
}

/** When recording began, if within the period: the hatched bars before it. */
function Counted({ data, metric }: { data: AudienceTrends; metric: Metric }) {
  const day = useDay();
  const since = data.counted_since[metric];
  const start = splitPeriods(data).now[0]?.from;
  if (start === undefined || since <= start) return null;
  const from = day(since);
  return (
    <p className={css.note}>
      <Trans>Раньше {from} бот этого не записывал: заштрихованные дни не считали.</Trans>
    </p>
  );
}

function FunnelCard({ data }: { data: AudienceTrends }) {
  const { t, i18n } = useLingui();
  const f = data.funnel;
  const fresh = data.funnel_new;
  const came = f.started_bot + f.opened_app - f.both;
  const fromChats = came - f.not_from_chats;
  const share = percent(fromChats, f.seen_in_chats, i18n.locale);
  const steps: Step[] = [
    {
      key: 'chats',
      title: t`Видели в чатах`,
      who: (
        <Trans>
          Писали в чате за последние 180 дней, просились в чат или состоят в нём, по
          данным бота.
        </Trans>
      ),
      count: f.seen_in_chats,
    },
    {
      key: 'came',
      title: t`Пришли к нам`,
      who: (
        <Trans>
          Хоть раз дали боту писать (Start, сообщение боту, разрешение в Mini App) или
          открыли Mini App. Из них {fromChats} бот видел в чатах, {f.not_from_chats} в
          чатах не видел.
        </Trans>
      ),
      count: came,
      share: <Trans>{share} видевших</Trans>,
    },
  ];
  return (
    <div className={css.card}>
      <Label aside={<Trans>за всё время</Trans>}>
        <Trans>От чата к нам</Trans>
      </Label>
      <FunnelSteps steps={steps} extra={{ came: <Overlap funnel={f} /> }} />
      <p className={css.who}>
        <Trans>
          За период: +{fresh.started_bot} дали боту писать, +{fresh.opened_app} впервые
          открыли Mini App.
        </Trans>
      </p>
      <Label aside={<Trans>сейчас</Trans>}>
        <Trans>Может ли бот им написать</Trans>
      </Label>
      <div className={css.side}>
        <div>
          <b>{f.reachable}</b>
          <Trans>можно написать: дали боту писать и не заблокировали</Trans>
        </div>
        <div>
          <b>{f.blocked}</b>
          <Trans>заблокировали бота</Trans>
        </div>
        <div>
          <b>{f.opted_out}</b>
          <Trans>отписались от новостей</Trans>
        </div>
        <div>
          <b>{f.opened_app - f.both}</b>
          <Trans>открывали Mini App, но писать боту не разрешили</Trans>
        </div>
      </div>
      {f.estimate > 0 ? (
        <p className={css.estimate}>
          <Trans>
            Ещё {f.estimate} — догадка переноса: старые записи бота, по которым похоже,
            что человек писал боту в личку. Проверить нельзя, сами они с тех пор не
            появлялись. В цифры выше не входят.
          </Trans>
        </p>
      ) : null}
    </div>
  );
}

type By = 'chats' | 'languages' | 'sources';

/** What a segment's key means to a reader: our links' labels, a missing language, the folded rest. */
function useSegmentLabel(): (by: By, row: Segment) => string {
  const { t } = useLingui();
  const sources: Record<string, string> = {
    '': t`без метки`,
    'backfill:dm_estimate': t`догадка переноса, потом пришли сами`,
    welcome: t`кнопка в приветствии чата`,
    captcha: t`сообщение капчи`,
    chats: t`кнопка «Чаты» в боте`,
    offer: t`ссылка «Предложить помощь»`,
  };
  return (by, row) => {
    if (row.key === REST) {
      const rest = row.label;
      return by === 'chats' ? t`ещё чатов: ${rest}` : t`остальные: ${rest}`;
    }
    if (by === 'languages') return row.key || t`не указан`;
    if (by === 'sources') {
      const university = row.key.startsWith('uni-') ? row.key.slice(4) : null;
      if (university) return t`ссылка на чаты вуза ${university}`;
      return sources[row.key] ?? row.key;
    }
    return row.label;
  };
}

function Segments({ data }: { data: AudienceTrends }) {
  const { t } = useLingui();
  const label = useSegmentLabel();
  const [by, setBy] = useState<By>('chats');
  const who = {
    chats: (
      <Trans>
        Пришедшие к нам — по чату, где бот впервые видел, как они пишут или просятся.
      </Trans>
    ),
    languages: <Trans>Пришедшие к нам — по языку их Telegram.</Trans>,
    sources: <Trans>Пришедшие к нам — по ссылке, с которой они пришли впервые.</Trans>,
  }[by];
  return (
    <div className={css.card}>
      <Label aside={<Trans>за всё время</Trans>}>
        <Trans>Откуда люди</Trans>
      </Label>
      <Segmented
        value={by}
        label={t`Разрез`}
        options={[
          { value: 'chats', label: t`Чат` },
          { value: 'languages', label: t`Язык` },
          { value: 'sources', label: t`Ссылка` },
        ]}
        onChange={(value) => {
          hapticSelection();
          setBy(value);
        }}
      />
      <p className={css.who}>{who}</p>
      <SegmentBars
        rows={data.segments[by].map((row) => ({ ...row, label: label(by, row) }))}
      />
    </div>
  );
}

function Links() {
  const navigate = useNavigate();
  return (
    <div style={{ marginTop: 16 }}>
      <Rows>
        <Row
          leading={
            <Tile tone={3}>
              <PersonIcon size={19} />
            </Tile>
          }
          title={<Trans>Все люди</Trans>}
          hint={<Trans>список, поиск, фильтры</Trans>}
          trailing={<Chevron />}
          onClick={() => {
            hapticSelection();
            navigate('/console/audience/people');
          }}
        />
      </Rows>
    </div>
  );
}
