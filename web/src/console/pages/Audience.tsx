import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router';

import { PersonIcon } from '@/components/icons';
import {
  Chevron,
  Chips,
  ChipView,
  Label,
  Row,
  Rows,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import css from '@/console/Audience.module.css';
import { useAudienceLabels } from '@/console/AudienceLabels';
import {
  bars,
  reachSegments,
  STATUSES,
  type Touchpoint,
  topLanguages,
} from '@/console/audience';
import { useBrowserConsole } from '@/console/browserContext';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { audienceSummaryQuery } from '@/console/queries';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * Who has ever used our bots or the Mini App: how many, whether the main bot
 * may write to them, where they came from and when. The list is a level down.
 * Nothing here sends anything.
 */
export default function ConsoleAudiencePage() {
  return (
    <ConsoleGate>
      <Title>
        <Trans>Аудитория</Trans>
      </Title>
      <AudienceSummaryView />
    </ConsoleGate>
  );
}

function AudienceSummaryView() {
  const { t } = useLingui();
  const navigate = useNavigate();
  const labels = useAudienceLabels();
  const inBrowser = useBrowserConsole();
  const { data, isPending, error, refetch } = useQuery(audienceSummaryQuery);

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

  const people = (params: Record<string, string> = {}) => {
    hapticSelection();
    const query = new URLSearchParams(params).toString();
    navigate(`/console/audience/people${query ? `?${query}` : ''}`);
  };
  const segments = reachSegments(data.reach);
  const languages = topLanguages(data.languages, 4);
  const busiestWeek = Math.max(1, ...data.new_by_week);

  const intro = (
    <div style={{ marginTop: 6 }}>
      <Sub>
        <Trans>Кто к нам приходил и кому основной бот сможет написать.</Trans>
      </Sub>
    </div>
  );
  const reach = (
    <div className={ui.reach}>
      <div className={ui.reachTotal}>
        <b>{data.total}</b>
        <Plural
          value={data.total}
          one="человек"
          few="человека"
          many="человек"
          other="человека"
        />
      </div>
      {segments.length > 0 ? (
        <div
          className={ui.reachBar}
          role="img"
          aria-label={segments
            .map((s) => `${labels.status[s.status]}: ${s.count}`)
            .join(', ')}
        >
          {segments.map((s) => (
            <span key={s.status} data-status={s.status} style={{ flex: s.count }} />
          ))}
        </div>
      ) : null}
      <div className={`${ui.reachLegend} ${css.legend}`}>
        {STATUSES.map((status) => (
          <button
            key={status}
            type="button"
            data-status={status}
            onClick={() => people({ status })}
          >
            <b>{data.reach[status]}</b> {labels.status[status]}
          </button>
        ))}
      </div>
    </div>
  );
  const sources = (
    <>
      <Label aside={t`первое касание`}>
        <Trans>Откуда приходят</Trans>
      </Label>
      <div className={ui.bars}>
        {bars(data.first_touch).map((row) => (
          <button
            key={row.key}
            type="button"
            className={ui.barRow}
            onClick={() => people({ touchpoint: row.key })}
          >
            <span>{labels.touchpoint[row.key as Touchpoint] ?? row.key}</span>
            <span className={ui.barTrack}>
              <span style={{ width: `${row.share * 100}%` }} />
            </span>
            <b>{row.count}</b>
          </button>
        ))}
      </div>
    </>
  );
  const weeks = (
    <>
      <Label aside={t`8 недель`}>
        <Trans>Новые по неделям</Trans>
      </Label>
      <div
        className={ui.weeks}
        role="img"
        aria-label={t`Новые люди по неделям, от старой к нынешней: ${data.new_by_week.join(', ')}`}
      >
        {data.new_by_week.map((count, week) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: the week is the identity.
            key={week}
            style={{ height: `${(count / busiestWeek) * 100}%` }}
          />
        ))}
      </div>
    </>
  );
  const languagesView = (
    <>
      {languages.top.length > 0 ? (
        <>
          <Label>
            <Trans>Язык Telegram</Trans>
          </Label>
          <Chips>
            {languages.top.map((language) => (
              <ChipView key={language.code}>
                {language.code} {language.count}
              </ChipView>
            ))}
            {languages.rest > 0 ? (
              <ChipView>
                <Trans>другие {languages.rest}</Trans>
              </ChipView>
            ) : null}
          </Chips>
        </>
      ) : null}
    </>
  );
  const links = (
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
          onClick={() => people()}
        />
        <Row
          leading={
            <Tile tone={0}>
              <PersonIcon size={19} />
            </Tile>
          }
          title={<Trans>Новые за неделю</Trans>}
          hint={
            <Plural
              value={data.new_this_week}
              one="# человек"
              few="# человека"
              many="# человек"
              other="# человека"
            />
          }
          trailing={<Chevron />}
          onClick={() => people({ new: 'week' })}
        />
      </Rows>
    </div>
  );

  if (inBrowser) {
    return (
      <div data-wide className={css.page}>
        {intro}
        {reach}
        <div className={css.grid}>
          <div className={css.card}>{sources}</div>
          <div className={css.card}>
            {weeks}
            {languagesView}
          </div>
        </div>
        {links}
      </div>
    );
  }
  return (
    <>
      {intro}
      {reach}
      {sources}
      {weeks}
      {languagesView}
      {links}
    </>
  );
}
