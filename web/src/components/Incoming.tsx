import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';

import { formatDay, PhraseView } from '@/components/Phrase';
import { Sheet } from '@/components/Sheet';
import {
  Action,
  Actions,
  AvatarView,
  Card,
  Cards,
  CLAMP_TWO_LINES,
  Empty,
  formatMoney,
  Reason,
  SkeletonRows,
  ui,
} from '@/components/Ui';
import { hapticSuccess } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';
import { requestName } from '@/lib/requestHeading';
import { responseDraft } from '@/lib/responseDraft';
import type { FeedRequest, ResponseCreate } from '@/lib/types';

/**
 * What people are asking for, for someone who could answer.
 *
 * The answer is written in a sheet over the list rather than on a screen of
 * its own: it is two sentences and a number, and making it a destination
 * would put a navigation either side of thirty seconds of typing. A sheet
 * also leaves the card where it was, unopened, for someone who only looked.
 */
export function Incoming() {
  const { i18n } = useLingui();
  const [answering, setAnswering] = useState<FeedRequest | null>(null);
  // What was typed survives the sheet closing: a tap beside it by mistake
  // must not cost the two sentences. Kept for one request, the last one.
  const [draft, setDraft] = useState<Draft>({ requestId: null, message: '', price: '' });
  const queryClient = useQueryClient();

  // Here rather than in the sheet: the sheet can be closed while an answer is
  // on its way, and one opened again must still see it as sending (or as
  // failed) instead of offering to send it a second time.
  const respond = useMutation({
    mutationFn: ({ requestId, body }: { requestId: number; body: ResponseCreate }) =>
      api.respondToRequest(requestId, body),
    onSuccess: (_, { requestId }) => {
      hapticSuccess();
      // The request drops out of the feed once answered, so the list is stale
      // the moment this succeeds.
      void queryClient.invalidateQueries({ queryKey: ['request-feed'] });
      // Only if it is still this request on screen: by now the person may
      // have closed the sheet and opened another one.
      setAnswering((open) => (open?.id === requestId ? null : open));
      setDraft((kept) =>
        kept.requestId === requestId ? { requestId: null, message: '', price: '' } : kept,
      );
    },
  });

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
    <>
      <Cards>
        {data.map((request) => (
          <FeedCard
            key={request.id}
            request={request}
            locale={i18n.locale}
            onRespond={() => {
              if (draft.requestId !== request.id) {
                setDraft({ requestId: request.id, message: '', price: '' });
              }
              setAnswering(request);
            }}
          />
        ))}
      </Cards>

      {answering ? (
        <RespondSheet
          request={answering}
          draft={draft}
          onDraft={setDraft}
          sending={respond.isPending && respond.variables?.requestId === answering.id}
          error={
            respond.isError && respond.variables?.requestId === answering.id
              ? respond.error
              : null
          }
          onSend={(body) => respond.mutate({ requestId: answering.id, body })}
          onClose={() => setAnswering(null)}
        />
      ) : null}
    </>
  );
}

interface Draft {
  requestId: number | null;
  message: string;
  price: string;
}

function From({ request }: { request: FeedRequest }) {
  const name = request.author_name;
  return <Trans>{name} просит помощи</Trans>;
}

function FeedCard({
  request,
  locale,
  onRespond,
}: {
  request: FeedRequest;
  locale: string;
  onRespond: () => void;
}) {
  // Without a subject or institution the text is the heading, and says
  // itself once: printing it again as the body made every such card read twice.
  const name = requestName(request);

  return (
    <Card>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <AvatarView avatar={request.author} size={34} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div className={ui.requestFrom}>
            <From request={request} />
            {request.deadline_on ? (
              <>
                {' · '}
                <Trans>до {formatDay(request.deadline_on, locale)}</Trans>
              </>
            ) : null}
          </div>
          <div className={ui.cardName} style={CLAMP_TWO_LINES}>
            {name ?? request.text}
          </div>
        </div>
        {request.budget?.amount != null ? (
          <div className={ui.priceAmount} style={{ flex: 'none' }}>
            {formatMoney(request.budget.amount)} {request.budget.currency}
          </div>
        ) : null}
      </div>

      {/* The words they typed, not our parse of them — two lines here, all
          of them in the sheet. */}
      {name ? (
        <p
          style={{
            margin: '8px 0 0',
            fontSize: 13,
            lineHeight: 1.45,
            color: 'var(--ink-soft)',
            ...CLAMP_TWO_LINES,
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

      <Actions>
        {/* Quiet: the list is a page of these, and a column of filled
            buttons reads as a wall rather than as a choice. The filled one
            is the send inside the sheet, where there is exactly one. */}
        <Action quiet onClick={onRespond}>
          <Trans>Откликнуться</Trans>
        </Action>
      </Actions>
    </Card>
  );
}

function RespondSheet({
  request,
  draft,
  onDraft,
  sending,
  error,
  onSend,
  onClose,
}: {
  request: FeedRequest;
  draft: Draft;
  onDraft: (draft: Draft) => void;
  sending: boolean;
  error: unknown;
  onSend: (body: ResponseCreate) => void;
  onClose: () => void;
}) {
  const { t } = useLingui();
  const messageId = useId();
  const priceId = useId();
  const payload = responseDraft(draft.message, draft.price);

  const name = request.author_name;

  return (
    <Sheet
      title={<Trans>Отклик на заявку</Trans>}
      onClose={onClose}
      closeLabel={t`Закрыть`}
    >
      <div className={ui.requestQuote}>
        <span className={ui.requestFrom}>
          <From request={request} />
        </span>
        <span className={ui.requestQuoteText}>{request.text}</span>
      </div>

      <div className={ui.respondForm}>
        <label className={ui.fieldLabel} htmlFor={messageId}>
          <Trans>Сообщение автору</Trans>
        </label>
        <div
          className={`${ui.field} ${ui.fieldOutlined}`}
          style={{ alignItems: 'flex-start' }}
        >
          <textarea
            id={messageId}
            value={draft.message}
            onChange={(event) => onDraft({ ...draft, message: event.target.value })}
            placeholder={t`Чем можешь помочь и когда`}
            rows={3}
            maxLength={1000}
            style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.4 }}
          />
        </div>

        <label className={ui.fieldLabel} htmlFor={priceId}>
          <Trans>
            Цена за час, Kč <span className={ui.fieldLabelNote}>необязательно</span>
          </Trans>
        </label>
        <div className={`${ui.field} ${ui.fieldOutlined}`}>
          <input
            id={priceId}
            value={draft.price}
            onChange={(event) => onDraft({ ...draft, price: event.target.value })}
            // Numeric keypad without the spinner arrows a number input adds.
            inputMode="decimal"
            style={{ all: 'unset', width: '100%' }}
          />
        </div>
      </div>

      {error ? (
        <Reason weak>
          <RespondError error={error} />
        </Reason>
      ) : null}

      <Actions>
        <Action
          onClick={() => {
            if (payload) onSend(payload);
          }}
          disabled={!payload || sending}
        >
          <Trans>Отправить отклик</Trans>
        </Action>
      </Actions>

      <div className={ui.sheetFoot}>
        <p className={`${ui.hint} ${ui.sheetOutcome}`}>
          <Trans>
            {name} увидит отклик в своей заявке и сможет написать тебе в Telegram.
          </Trans>
        </p>
      </div>
    </Sheet>
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
