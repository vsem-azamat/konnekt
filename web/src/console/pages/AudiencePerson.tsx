import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useParams } from 'react-router';

import {
  Action,
  Chips,
  ChipView,
  Hint,
  Label,
  Letters,
  Row,
  Rows,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { useAudienceLabels } from '@/console/AudienceLabels';
import { ESTIMATE_SOURCE, reachOf } from '@/console/audience';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { audiencePersonQuery } from '@/console/queries';
import { personName, utc } from '@/console/session';
import { initials } from '@/lib/chats';

/** One person: where they have been, and whether each bot may write to them. */
export default function ConsoleAudiencePersonPage() {
  const id = Number(useParams().id);
  return (
    <ConsoleGate>
      <Person id={id} />
    </ConsoleGate>
  );
}

function Person({ id }: { id: number }) {
  const { t, i18n } = useLingui();
  const labels = useAudienceLabels();
  const { data, isPending, error, refetch } = useQuery(audiencePersonQuery(id));

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

  const name = personName(data);
  const date = (iso: string) =>
    i18n.date(utc(iso), { day: 'numeric', month: 'short', year: 'numeric' });
  const moment = (iso: string) =>
    i18n.date(utc(iso), {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  const reachLine = (bot: string) => {
    const row = data.reach.find((r) => r.bot === bot);
    switch (reachOf(data.reach, bot)) {
      case 'open':
        return <Trans>может писать, с {date(row?.started_at ?? '')}</Trans>;
      case 'blocked':
        return <Trans>заблокирован {date(row?.blocked_at ?? '')}</Trans>;
      default:
        return <Trans>не запускали</Trans>;
    }
  };
  // Each touchpoint's first and latest visit, newest first.
  const events = data.touches
    .flatMap((touch) => [
      { at: touch.first_at, first: true, touchpoint: touch.touchpoint },
      ...(touch.last_at !== touch.first_at
        ? [{ at: touch.last_at, first: false, touchpoint: touch.touchpoint }]
        : []),
    ])
    .sort((a, b) => b.at.localeCompare(a.at));

  return (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <Tile tone={2} large>
          <Letters text={initials(name.replace('@', ''))} />
        </Tile>
        <div>
          <Title>{name}</Title>
          <Sub>
            {[data.username ? `@${data.username}` : null, `id ${data.user_id}`]
              .filter(Boolean)
              .join(' · ')}
          </Sub>
        </div>
      </div>
      <div style={{ marginTop: 12 }}>
        <Chips>
          <ChipView>
            <span className={ui.statusText} data-status={data.status}>
              {labels.status[data.status]}
            </span>
          </ChipView>
          {data.language_code ? (
            <ChipView>
              <Trans>язык {data.language_code}</Trans>
            </ChipView>
          ) : null}
          {data.is_premium ? <ChipView>Premium</ChipView> : null}
        </Chips>
      </div>
      {data.username ? (
        <div className={ui.actionsStacked}>
          <Action onClick={() => openTelegramLink(`https://t.me/${data.username}`)}>
            <Trans>Открыть в Telegram</Trans>
          </Action>
        </div>
      ) : null}

      <Label>
        <Trans>Где бывает</Trans>
      </Label>
      <Rows>
        {data.touches.map((touch) => (
          <Row
            key={touch.touchpoint}
            title={labels.touchpoint[touch.touchpoint] ?? touch.touchpoint}
            hint={
              <Trans>
                с {date(touch.first_at)}, последний раз {date(touch.last_at)}
              </Trans>
            }
            trailing={<span className={ui.count}>{touch.count}</span>}
          />
        ))}
        {data.source ? (
          <Row
            title={<Trans>Пришли по ссылке</Trans>}
            hint={
              data.source === ESTIMATE_SOURCE ? t`оценка по старым данным` : data.source
            }
          />
        ) : null}
      </Rows>

      <Label>
        <Trans>Может ли бот написать</Trans>
      </Label>
      <Rows>
        <Row title={labels.touchpoint.main_bot} hint={reachLine('main_bot')} />
        <Row title={labels.touchpoint.contact_bot} hint={reachLine('contact_bot')} />
        <Row
          title={<Trans>Рассылки</Trans>}
          hint={
            data.opted_out_at ? (
              <Trans>отписались {date(data.opted_out_at)}</Trans>
            ) : (
              <Trans>не отписывались</Trans>
            )
          }
        />
      </Rows>

      <Label>
        <Trans>История</Trans>
      </Label>
      <div className={ui.timeline}>
        {events.map((event) => (
          <div key={`${event.touchpoint}-${event.first}`}>
            {event.first ? (
              <Trans>
                Впервые: {labels.touchpoint[event.touchpoint] ?? event.touchpoint}
              </Trans>
            ) : (
              <Trans>
                Последний раз: {labels.touchpoint[event.touchpoint] ?? event.touchpoint}
              </Trans>
            )}
            <small>{moment(event.at)}</small>
          </div>
        ))}
      </div>
      <Hint>
        <Trans>
          Тексты сообщений не хранятся: только то, что сообщает Telegram, и когда человек
          приходил.
        </Trans>
      </Hint>
    </>
  );
}
