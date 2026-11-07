import { Trans, useLingui } from '@lingui/react/macro';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { type ReactNode, useState } from 'react';

import { Label, Segmented, SkeletonRows, Sub, Title } from '@/components/Ui';
import audience from '@/console/Audience.module.css';
import { SegmentBars, useDay } from '@/console/AudienceCharts';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { sourcesQuery } from '@/console/queries';
import css from '@/console/Usage.module.css';
import { useUsageLabels } from '@/console/UsageLabels';
import {
  position,
  SOURCES_PERIODS,
  type Sources,
  type SourcesPeriod,
  WHOLE,
} from '@/console/usage';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * Where the site's visitors come from and what they searched for in Google,
 * and how many of them the site's buttons brought into the Mini App. The
 * site and search are imported from Cloudflare and Search Console a few
 * times a day (app/usage/sources.py); until one is connected its card says
 * so rather than showing zeros.
 */
export default function ConsoleSourcesPage() {
  return (
    <ConsoleGate wide>
      <Title>
        <Trans>Источники</Trans>
      </Title>
      <SourcesView />
    </ConsoleGate>
  );
}

function SourcesView() {
  const [days, setDays] = useState<SourcesPeriod>(30);
  const { data, isPending, error, refetch } = useQuery({
    ...sourcesQuery(days),
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

function Report({
  data,
  days,
  setDays,
}: {
  data: Sources;
  days: SourcesPeriod;
  setDays: (days: SourcesPeriod) => void;
}) {
  const { t } = useLingui();
  return (
    <div>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>
            Сайт konnekt.cz и поиск Google. Период кончается вчера: сегодняшний день ещё
            не пришёл.
          </Trans>
        </Sub>
      </div>
      <div className={audience.period}>
        <Segmented
          value={String(days)}
          label={t`Период`}
          options={SOURCES_PERIODS.map((p) => ({
            value: String(p),
            label: t`${p} дней`,
          }))}
          onChange={(value) => {
            hapticSelection();
            setDays(Number(value) as SourcesPeriod);
          }}
        />
      </div>
      <Tiles data={data} />
      <div className={css.grid}>
        <Site data={data} />
        <Search data={data} />
        <ToApp data={data} />
      </div>
    </div>
  );
}

function Tiles({ data }: { data: Sources }) {
  const { i18n } = useLingui();
  const off = <span className={css.tileHint}>—</span>;
  const clicks = i18n.number(data.search.clicks);
  return (
    <div className={css.tiles} data-three>
      <Tile
        label={<Trans>посетителей сайта</Trans>}
        value={data.site.on ? data.site.visits : '—'}
        hint={data.site.on ? <Trans>визитов</Trans> : off}
      />
      <Tile
        label={<Trans>запусков с сайта</Trans>}
        value={data.to_app.launches}
        hint={<Trans>в Mini App</Trans>}
      />
      <Tile
        label={<Trans>показов в Google</Trans>}
        value={data.search.on ? data.search.impressions : '—'}
        hint={data.search.on ? <Trans>кликов: {clicks}</Trans> : off}
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

function Through({ through }: { through: string | null }) {
  const day = useDay();
  if (!through) {
    return (
      <span className={css.through}>
        <Trans>данные ещё не пришли</Trans>
      </span>
    );
  }
  const last = day(through);
  return (
    <span className={css.through}>
      <Trans>данные по {last}</Trans>
    </span>
  );
}

function Site({ data }: { data: Sources }) {
  const { t } = useLingui();
  const site = data.site;
  if (!site.on) {
    return (
      <div className={`${audience.card} ${css.wide}`}>
        <Label>
          <Trans>Откуда пришли на сайт</Trans>
        </Label>
        <p className={css.notice}>
          <Trans>
            <b>Cloudflare Web Analytics не подключён.</b> Включите Web Analytics для
            konnekt.cz в Cloudflare и выдайте ключ для чтения; тогда здесь появятся
            посетители, откуда они пришли и какие страницы смотрели.
          </Trans>
        </p>
      </div>
    );
  }
  const referrer = (key: string) => (key === WHOLE ? t`прямые и без источника` : key);
  return (
    <>
      <div className={audience.card}>
        <Label aside={<Through through={site.through} />}>
          <Trans>Откуда пришли на сайт</Trans>
        </Label>
        <p className={audience.who}>
          <Trans>Визиты по сайту, с которого перешли. Cloudflare, без cookies.</Trans>
        </p>
        <SegmentBars
          rows={site.referrers.map((r) => ({
            key: r.key,
            label: referrer(r.key),
            people: r.visits,
          }))}
        />
      </div>
      <div className={audience.card}>
        <Label aside={<Through through={site.through} />}>
          <Trans>Страницы</Trans>
        </Label>
        <p className={audience.who}>
          <Trans>Визиты по странице сайта.</Trans>
        </p>
        <SegmentBars
          rows={site.pages.map((p) => ({ key: p.key, label: p.key, people: p.visits }))}
        />
      </div>
    </>
  );
}

function Search({ data }: { data: Sources }) {
  const { i18n } = useLingui();
  const search = data.search;
  if (!search.on) {
    return (
      <div className={`${audience.card} ${css.wide}`}>
        <Label>
          <Trans>Что искали в Google</Trans>
        </Label>
        <p className={css.notice}>
          <Trans>
            <b>Search Console не подключён.</b> Добавьте наш служебный аккаунт
            пользователем в Search Console для konnekt.cz; тогда здесь появятся запросы,
            клики и показы.
          </Trans>
        </p>
      </div>
    );
  }
  return (
    <div className={`${audience.card} ${css.wide}`}>
      <Label aside={<Through through={search.through} />}>
        <Trans>Что искали в Google</Trans>
      </Label>
      <p className={audience.who}>
        <Trans>
          Запросы, по которым сайт показывали в Google. Редкие запросы Google не называет,
          поэтому строки в сумме меньше итога.
        </Trans>
      </p>
      {search.queries.length === 0 ? (
        <p className={audience.empty}>
          <Trans>Пока ни одного запроса.</Trans>
        </p>
      ) : (
        <div className={css.table}>
          <table>
            <thead>
              <tr>
                <th>
                  <Trans>Запрос</Trans>
                </th>
                <th>
                  <Trans>Клики</Trans>
                </th>
                <th>
                  <Trans>Показы</Trans>
                </th>
                <th>
                  <Trans>Место</Trans>
                </th>
              </tr>
            </thead>
            <tbody>
              {search.queries.map((q) => (
                <tr key={q.query}>
                  <td>{q.query}</td>
                  <td>{i18n.number(q.clicks)}</td>
                  <td>{i18n.number(q.impressions)}</td>
                  <td>{position(q.position, i18n.locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ToApp({ data }: { data: Sources }) {
  const labels = useUsageLabels();
  return (
    <div className={`${audience.card} ${css.wide}`}>
      <Label aside={<Trans>запусков</Trans>}>
        <Trans>С сайта в Mini App</Trans>
      </Label>
      <p className={audience.who}>
        <Trans>
          Запуски приложения по кнопкам сайта, по метке кнопки. Считает само приложение.
        </Trans>
      </p>
      <SegmentBars
        rows={data.to_app.by_source.map((s) => ({
          key: s.source,
          label: labels.source(s.source),
          people: s.launches,
        }))}
      />
    </div>
  );
}
