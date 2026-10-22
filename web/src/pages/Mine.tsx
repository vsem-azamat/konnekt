import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { Incoming } from '@/components/Incoming';
import { DocumentIcon, iconForService } from '@/components/icons';
import { formatDay } from '@/components/Phrase';
import { RemoveRequest } from '@/components/RemoveRequest';
import {
  Action,
  Actions,
  AvatarStack,
  Card,
  Cards,
  CLAMP_TWO_LINES,
  Empty,
  Reason,
  Screen,
  Segmented,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { buckets, daysLeft, localDay } from '@/lib/requestBuckets';
import { requestName } from '@/lib/requestHeading';
import type { HelpRequest } from '@/lib/types';

type Tab = 'mine' | 'incoming';
type List = 'open' | 'closed';

/**
 * Both directions of the same relationship.
 *
 * What you asked for, and — if you are also a helper — what other people are
 * asking for. One screen rather than two tabs: the two are the same person's
 * business, and most people will only ever see the first.
 *
 * The title names what is on the screen. "Мои" answers neither "whose" nor
 * "what", and a tab label is the one place there is no room to explain.
 */
export default function MinePage() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  // In the URL, so the notification that brings a helper back can land on the
  // right half and a reload does not lose it.
  const [params, setParams] = useSearchParams();

  const me = useQuery({ queryKey: ['me'], queryFn: ({ signal }) => api.getMe(signal) });
  const isHelper = me.data?.is_helper ?? false;

  // Forced back to 'mine' for someone who is not a helper: the control that
  // switches back is only rendered for helpers, so /mine?tab=incoming would
  // otherwise strand them on "fill in your profile" with no way out.
  const tab: Tab = isHelper && params.get('tab') === 'incoming' ? 'incoming' : 'mine';

  // Closed requests are the second list, also in the URL: Back from a closed
  // request returns to the closed ones.
  const list: List = params.get('list') === 'closed' ? 'closed' : 'open';

  // Rebuilt from the current params rather than replaced: a wholesale object
  // drops every other search parameter on the screen.
  const setParam = (key: string, value: string | null) => {
    const updated = new URLSearchParams(params);
    if (value === null) updated.delete(key);
    else updated.set(key, value);
    setParams(updated, { replace: true });
  };
  const switchTo = (next: Tab) => setParam('tab', next === 'mine' ? null : next);
  const switchList = (next: List) => setParam('list', next === 'open' ? null : next);

  // The request whose «Убрать заявку» is open, from the «Закрыть» on its card.
  const [removing, setRemoving] = useState<number | null>(null);

  const { data, isPending, isError } = useQuery({
    queryKey: ['requests'],
    queryFn: ({ signal }) => api.getRequests(signal),
  });
  const { open, closed } = buckets(data ?? []);
  const shown = list === 'open' ? open : closed;

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Заявки</Trans>
      </Title>

      {isHelper ? (
        <div style={{ marginTop: 14 }}>
          <Segmented<Tab>
            value={tab}
            onChange={switchTo}
            options={[
              { value: 'mine', label: <Trans>Мои заявки</Trans> },
              { value: 'incoming', label: <Trans>Входящие</Trans> },
            ]}
          />
        </div>
      ) : null}

      {/* The title already says «Заявки»; a section label repeating it under
            the same words told the reader nothing. */}
      <div style={{ height: 14 }} />

      {tab === 'incoming' ? (
        <Incoming />
      ) : isPending ? (
        <SkeletonRows count={2} />
      ) : isError ? (
        <Empty title={<Trans>Не получилось загрузить</Trans>} />
      ) : data.length === 0 ? (
        <Empty
          title={<Trans>Заявок пока нет</Trans>}
          body={
            <Trans>
              Опиши, что нужно, и получай отклики — вместо того чтобы искать самому.
            </Trans>
          }
          action={
            <Action
              onClick={() => {
                hapticSelection();
                navigate('/ask');
              }}
            >
              <Trans>Мне нужна помощь</Trans>
            </Action>
          }
        />
      ) : (
        <>
          <Segmented<List>
            value={list}
            onChange={switchList}
            options={[
              { value: 'open', label: <Trans>Открытые · {open.length}</Trans> },
              { value: 'closed', label: <Trans>Закрытые · {closed.length}</Trans> },
            ]}
          />
          <div style={{ height: 14 }} />
          {shown.length === 0 ? (
            <Empty
              title={
                list === 'open' ? (
                  <Trans>Открытых заявок нет</Trans>
                ) : (
                  <Trans>Закрытых заявок нет</Trans>
                )
              }
            />
          ) : (
            <Cards>
              {shown.map((request) => (
                <RequestCard
                  key={request.id}
                  request={request}
                  locale={i18n.locale}
                  onClick={() => navigate(`/request/${request.id}`)}
                  onRemove={() => setRemoving(request.id)}
                />
              ))}
            </Cards>
          )}
        </>
      )}

      {removing === null ? null : (
        <RemoveRequest requestId={removing} canClose onClose={() => setRemoving(null)} />
      )}
    </Screen>
  );
}

function RequestCard({
  request,
  locale,
  onClick,
  onRemove,
}: {
  request: HelpRequest;
  locale: string;
  onClick: () => void;
  onRemove: () => void;
}) {
  const Icon = request.service_type ? iconForService('tutoring') : DocumentIcon;
  const title = requestName(request) ?? request.text;
  const isOpen = request.status === 'open';

  const body = (
    <>
      <div className={ui.cardTop}>
        <Tile tone={request.id % 6}>
          <Icon size={19} />
        </Tile>
        <div style={{ minWidth: 0 }}>
          <div
            style={{
              fontSize: 14.5,
              fontWeight: 680,
              letterSpacing: '-0.015em',
              // A request with no subject is titled by its own text, which can
              // run to a thousand characters; the card opens to the whole of it.
              ...CLAMP_TWO_LINES,
            }}
          >
            {title}
          </div>
          <div className={ui.cardMeta}>
            {isOpen ? (
              <span>
                {request.deadline_on ? (
                  <Trans>до {formatDay(request.deadline_on, locale)}</Trans>
                ) : (
                  <Trans>без срока</Trans>
                )}
                {/* A deadline already says how long; the days left are for a
                    request without one, which ends when its time runs out. */}
                {!request.deadline_on && request.expires_at ? (
                  <>
                    {' · '}
                    <Plural
                      value={daysLeft(request.expires_at)}
                      one="ещё # день"
                      few="ещё # дня"
                      many="ещё # дней"
                      other="ещё # дня"
                    />
                  </>
                ) : null}
              </span>
            ) : (
              <>
                <span className={ui.status}>
                  <Trans>Закрыта</Trans>
                </span>
                {/* The deadline itself when there was one: its expiry is the
                    last instant of that day in UTC, the next day in Prague. */}
                {request.status === 'expired' &&
                (request.deadline_on || request.expires_at) ? (
                  <span>
                    <Trans>
                      срок вышел{' '}
                      {formatDay(
                        request.deadline_on ?? localDay(request.expires_at ?? ''),
                        locale,
                      )}
                    </Trans>
                  </span>
                ) : request.closed_at ? (
                  <span>
                    <Trans>
                      закрыта {formatDay(localDay(request.closed_at), locale)}
                    </Trans>
                  </span>
                ) : null}
              </>
            )}
          </div>
        </div>
      </div>

      {request.responses_count > 0 ? (
        <div className={ui.reasonRow}>
          <Reason>
            <Plural
              value={request.responses_count}
              one="# отклик"
              few="# отклика"
              many="# откликов"
              other="# отклика"
            />
          </Reason>
          <AvatarStack avatars={request.responders} />
        </div>
      ) : (
        <Reason weak>
          {isOpen ? <Trans>Пока без откликов</Trans> : <Trans>Без откликов</Trans>}
        </Reason>
      )}
    </>
  );

  if (!isOpen) {
    return (
      <div className={ui.cardDim}>
        <Card onClick={onClick}>{body}</Card>
      </div>
    );
  }

  // «Закрыть» is a button of its own, and a button cannot hold another, so the
  // card is a box holding two: the request, and the way to remove it.
  return (
    <div className={ui.card}>
      <button
        type="button"
        className={`${ui.cardPress} ${ui.pressable}`}
        onClick={onClick}
      >
        {body}
      </button>
      {/* Asks rather than closes: the same sheet as «⋯» on the request, where
          deleting is the other answer. */}
      <Actions>
        <Action quiet onClick={onRemove}>
          <Trans context="request">Закрыть</Trans>
        </Action>
      </Actions>
    </div>
  );
}
