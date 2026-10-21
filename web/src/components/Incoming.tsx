import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { formatDay, PhraseView } from '@/components/Phrase';
import {
  Action,
  Actions,
  AvatarView,
  Card,
  Cards,
  Empty,
  formatMoney,
  Reason,
  SkeletonRows,
  ui,
} from '@/components/Ui';
import { hapticSuccess } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';
import { requestName } from '@/lib/requestHeading';
import type { FeedRequest } from '@/lib/types';

/** Two lines until the card is opened. */
const CLAMP = {
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
} as const;

/**
 * What people are asking for, for someone who could answer.
 *
 * The composer is inside the card rather than on a screen of its own: an
 * answer is two sentences and a number, and making it a destination would put
 * a navigation either side of thirty seconds of typing.
 */
export function Incoming() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  const [openId, setOpenId] = useState<number | null>(null);

  const { data, isPending, isError, error } = useQuery({
    queryKey: ['request-feed'],
    queryFn: ({ signal }) => api.getRequestFeed(signal),
  });

  // 403 is not a failure here: it is the answer for someone who has no helper
  // profile, and the useful response is the invitation to make one.
  if (isError && error instanceof ApiError && error.status === 403) {
    return (
      <Empty
        title={<Trans>Сначала заполни профиль</Trans>}
        body={<Trans>Заявки видят те, кто может на них ответить.</Trans>}
      />
    );
  }

  if (isPending) return <SkeletonRows count={3} />;
  if (isError) return <Empty title={<Trans>Не получилось загрузить</Trans>} />;
  if (data.length === 0) {
    return (
      <Empty
        title={<Trans>Пока никто ничего не просит</Trans>}
        body={
          <Trans>
            Здесь появятся заявки со всего каталога. Те, что по твоим предметам, будут
            выше.
          </Trans>
        }
      />
    );
  }

  return (
    <Cards>
      {data.map((request) => (
        <FeedCard
          key={request.id}
          request={request}
          locale={i18n.locale}
          isOpen={openId === request.id}
          onToggle={() => setOpenId(openId === request.id ? null : request.id)}
          onDone={() => {
            setOpenId(null);
            navigate('/mine?tab=incoming');
          }}
        />
      ))}
    </Cards>
  );
}

function FeedCard({
  request,
  locale,
  isOpen,
  onToggle,
  onDone,
}: {
  request: FeedRequest;
  locale: string;
  isOpen: boolean;
  onToggle: () => void;
  onDone: () => void;
}) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const [message, setMessage] = useState('');
  const [price, setPrice] = useState('');

  const respond = useMutation({
    mutationFn: () =>
      api.respondToRequest(request.id, {
        message: message.trim(),
        // An empty field means "did not say", not zero.
        price_amount: price.trim() ? Number(price) : undefined,
        price_unit: price.trim() ? 'hour' : undefined,
      }),
    onSuccess: () => {
      hapticSuccess();
      // The request drops out of the feed once answered, so the list is stale
      // the moment this succeeds.
      void queryClient.invalidateQueries({ queryKey: ['request-feed'] });
      onDone();
    },
  });

  // Without a subject or institution the text is the heading, and says
  // itself once: printing it again as the body made every such card read twice.
  const name = requestName(request);
  const amount = Number(price);
  const priceValid = !price.trim() || (Number.isFinite(amount) && amount >= 0);
  const ready = message.trim().length >= 3 && priceValid && !respond.isPending;

  return (
    <Card>
      {/* Not a <button> wrapping the whole card: a button may only contain
          phrasing content, and this holds paragraphs. The toggle is its own
          control at the bottom, which also makes the affordance explicit
          instead of "tap the card and find out". */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <AvatarView avatar={request.author} size={34} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className={ui.cardName} style={isOpen ? undefined : CLAMP}>
            {name ?? request.text}
          </div>
          <div style={{ marginTop: 2, fontSize: 12, color: 'var(--muted)' }}>
            {request.author_name}
            {request.deadline_on ? (
              <>
                {' · '}
                <Trans>до {formatDay(request.deadline_on, locale)}</Trans>
              </>
            ) : null}
          </div>
        </div>
        {request.budget?.amount != null ? (
          <div className={ui.priceAmount} style={{ flex: 'none' }}>
            {formatMoney(request.budget.amount)} {request.budget.currency}
          </div>
        ) : null}
      </div>

      {/* The words they typed, not our parse of them — collapsed to two
          lines until the card is opened. */}
      {name ? (
        <p
          style={{
            margin: '8px 0 0',
            fontSize: 13,
            lineHeight: 1.45,
            color: 'var(--ink-soft)',
            ...(isOpen ? {} : CLAMP),
          }}
        >
          {request.text}
        </p>
      ) : null}

      {request.reason ? (
        <Reason>
          <PhraseView phrase={request.reason} locale={locale} />
        </Reason>
      ) : null}

      {isOpen ? null : (
        <Actions>
          {/* Quiet: the list is a page of these, and a column of filled
              buttons reads as a wall rather than as a choice. The filled one
              is the send inside the composer, where there is exactly one. */}
          <Action quiet onClick={onToggle}>
            <Trans>Откликнуться</Trans>
          </Action>
        </Actions>
      )}

      {isOpen ? (
        <div style={{ marginTop: 12 }}>
          <div
            className={`${ui.field} ${ui.fieldOnCard}`}
            style={{ alignItems: 'flex-start' }}
          >
            <textarea
              value={message}
              onChange={(event) => setMessage(event.target.value)}
              placeholder={t`Чем можешь помочь и когда`}
              rows={3}
              maxLength={1000}
              style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.4 }}
            />
          </div>

          <div className={`${ui.field} ${ui.fieldOnCard}`} style={{ marginTop: 8 }}>
            <input
              value={price}
              onChange={(event) => setPrice(event.target.value)}
              placeholder={t`Цена за час, Kč — необязательно`}
              // Numeric keypad without the spinner arrows a number input adds.
              inputMode="decimal"
              style={{ all: 'unset', width: '100%' }}
            />
          </div>

          {respond.isError ? (
            <Reason weak>
              <RespondError error={respond.error} />
            </Reason>
          ) : null}

          <Actions>
            <Action onClick={() => respond.mutate()} disabled={!ready}>
              <Trans>Отправить</Trans>
            </Action>
            <Action quiet onClick={onToggle}>
              <Trans>Не сейчас</Trans>
            </Action>
          </Actions>
        </div>
      ) : null}
    </Card>
  );
}

/**
 * Why the answer did not go out.
 *
 * Three different things return 409 — the request closed while the composer
 * was open, this helper has answered before, and Telegram has no public
 * username to write back to — and each needs a different next step from the
 * reader, so the status code alone is not enough to pick a sentence.
 */
function RespondError({ error }: { error: unknown }) {
  if (!(error instanceof ApiError)) {
    return <Trans>Не отправилось — попробуй ещё раз</Trans>;
  }
  const detail =
    typeof error.detail === 'object' && error.detail !== null
      ? String((error.detail as { detail?: unknown }).detail ?? '')
      : '';

  if (error.status === 403) return <Trans>Сначала опубликуй профиль</Trans>;
  if (error.status === 409 && detail.includes('username')) {
    return <Trans>Заведи в Telegram публичный @username — иначе тебе не ответят</Trans>;
  }
  if (error.status === 409 && detail.includes('already')) {
    return <Trans>На эту заявку ты уже отвечал</Trans>;
  }
  if (error.status === 409) return <Trans>Заявку уже закрыли</Trans>;
  return <Trans>Не отправилось — попробуй ещё раз</Trans>;
}
