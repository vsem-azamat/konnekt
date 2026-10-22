import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useState } from 'react';
import { useParams } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { formatDay, PriceUnitLabel } from '@/components/Phrase';
import { Sheet } from '@/components/Sheet';
import {
  Action,
  Actions,
  AvatarView,
  Badge,
  Card,
  Cards,
  Empty,
  Hint,
  Label,
  PriceView,
  Reason,
  Screen,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSuccess } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { RequestResponse } from '@/lib/types';

/**
 * One request of yours, and who answered it.
 *
 * The list is the decision: each answer carries the price, what the person
 * said, and enough of their profile to judge it. Accepting does not close the
 * request — needing two people for two subjects is ordinary.
 */
export default function RequestPage() {
  const { id } = useParams();
  const requestId = Number(id);
  const { i18n } = useLingui();

  // From the list rather than its own endpoint: this screen is only ever
  // reached from it, so the request is already in the cache.
  const requests = useQuery({
    queryKey: ['requests'],
    queryFn: ({ signal }) => api.getRequests(signal),
  });
  const request = requests.data?.find((row) => row.id === requestId);

  // A path like /request/abc parses to NaN. Disabling the query on it leaves
  // `isPending` true for ever, so the screen would sit on a skeleton with no
  // way out — the id has to be checked before anything is rendered.
  const validId = Number.isInteger(requestId) && requestId > 0;

  const { data, isPending, isError } = useQuery({
    queryKey: ['responses', requestId],
    queryFn: ({ signal }) => api.getResponses(requestId, signal),
    enabled: validId,
  });

  if (!validId) {
    return (
      <Screen>
        <AppHeader />
        <Empty title={<Trans>Такой заявки нет</Trans>} />
      </Screen>
    );
  }

  return (
    <Screen>
      <AppHeader />
      <Title>{request?.subject ?? <Trans>Заявка</Trans>}</Title>

      {request ? (
        <>
          <Sub>{request.text}</Sub>
          {request.deadline_on ? (
            <Hint>
              <Trans>до {formatDay(request.deadline_on, i18n.locale)}</Trans>
            </Hint>
          ) : null}
        </>
      ) : null}

      <Label>
        <Trans>Отклики</Trans>
      </Label>

      {isPending ? (
        <SkeletonRows count={2} />
      ) : isError ? (
        <Empty title={<Trans>Не получилось загрузить</Trans>} />
      ) : data.length === 0 ? (
        <Empty
          title={<Trans>Откликов пока нет</Trans>}
          body={
            <Trans>Заявку видят все, кто предлагает помощь. Отклики приходят сюда.</Trans>
          }
        />
      ) : (
        <Cards>
          {data.map((response) => (
            <ResponseCard key={response.id} response={response} />
          ))}
        </Cards>
      )}
    </Screen>
  );
}

function ResponseCard({ response }: { response: RequestResponse }) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const [confirming, setConfirming] = useState(false);

  const settle = useMutation({
    mutationFn: (verdict: 'accept' | 'decline') =>
      verdict === 'accept'
        ? api.acceptResponse(response.id)
        : api.declineResponse(response.id),
    onSuccess: (updated) => {
      if (updated.status === 'accepted') hapticSuccess();
      void queryClient.invalidateQueries({
        queryKey: ['responses', response.request_id],
      });
    },
  });

  const write = () => {
    if (!response.username) return;
    openTelegramLink(`https://t.me/${response.username}`);
  };

  const name = response.name;
  const decided = response.status === 'accepted' || response.status === 'declined';

  return (
    <Card>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <AvatarView avatar={response.avatar} size={38} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 14.5, fontWeight: 680, letterSpacing: '-0.015em' }}>
              {response.name}
            </span>
            {response.status === 'accepted' ? (
              <Badge inline>
                <Trans>выбран</Trans>
              </Badge>
            ) : null}
          </div>
          {response.affiliation ? (
            <div style={{ marginTop: 2, fontSize: 12, color: 'var(--muted)' }}>
              {response.affiliation}
            </div>
          ) : null}
        </div>
        {response.price ? (
          <PriceView
            price={response.price}
            unitLabel={<PriceUnitLabel unit={response.price.unit} />}
          />
        ) : null}
      </div>

      <p
        style={{
          margin: '9px 0 0',
          fontSize: 13.5,
          lineHeight: 1.45,
          color: 'var(--ink-soft)',
        }}
      >
        {response.message}
      </p>

      {response.deals_count > 0 ? (
        <Reason>
          <Plural
            value={response.deals_count}
            one="# занятие через нас"
            few="# занятия через нас"
            many="# занятий через нас"
            other="# занятия через нас"
          />
        </Reason>
      ) : null}

      {response.status === 'declined' ? (
        <Reason weak>
          <Trans>Ты отказался</Trans>
        </Reason>
      ) : response.username ? (
        <Actions>
          {/* Writing is the point; accepting is what records that it happened,
              so both are offered and neither is buried. */}
          <Action tall onClick={write}>
            <Trans>Написать</Trans>
          </Action>
          {decided ? null : (
            <>
              <Action
                tall
                quiet
                onClick={() => setConfirming(true)}
                disabled={settle.isPending}
              >
                <Trans>Выбрать</Trans>
              </Action>
              <Action
                tall
                quiet
                onClick={() => settle.mutate('decline')}
                disabled={settle.isPending}
              >
                <Trans>Отказать</Trans>
              </Action>
            </>
          )}
        </Actions>
      ) : (
        // Answering requires a public username, so this only happens if the
        // person removed theirs afterwards. Saying so beats an empty row of
        // buttons that lead nowhere.
        <Reason weak>
          <Trans>У этого человека нет @username — написать не получится</Trans>
        </Reason>
      )}

      {/* Choosing tells the helper and cannot be taken back, so it asks once.
          Writing and declining do not: the first changes nothing, and the
          second is what the person came to do when they press it. */}
      {confirming ? (
        <Sheet
          title={t`Выбрать ${name}?`}
          closeLabel={t`Отмена`}
          onClose={() => setConfirming(false)}
        >
          <p className={ui.sheetNote}>
            <Trans>Помощник получит уведомление. Отменить нельзя.</Trans>
          </p>
          <Actions>
            <Action
              onClick={() =>
                settle.mutate('accept', { onSettled: () => setConfirming(false) })
              }
              disabled={settle.isPending}
            >
              <Trans>Выбрать</Trans>
            </Action>
            <Action quiet onClick={() => setConfirming(false)}>
              <Trans>Отмена</Trans>
            </Action>
          </Actions>
        </Sheet>
      ) : null}
    </Card>
  );
}
