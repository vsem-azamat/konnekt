import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useState } from 'react';
import { useSearchParams } from 'react-router';

import { formatDay, PhraseView, PriceUnitLabel } from '@/components/Phrase';
import { Sheet } from '@/components/Sheet';
import {
  Action,
  Actions,
  AvatarView,
  Card,
  Cards,
  ChipView,
  CLAMP_TWO_LINES,
  Empty,
  formatMoney,
  Reason,
  SkeletonRows,
  ui,
} from '@/components/Ui';
import { hapticSelection, hapticSuccess } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';
import {
  chipKey,
  defaultChip,
  type FeedChip,
  feedChips,
  feedQuery,
  feedSections,
} from '@/lib/feedChips';
import { requestName, requestQuote } from '@/lib/requestHeading';
import {
  type Draft,
  MESSAGE_MAX,
  openDraft,
  responseDraft,
  withStarter,
} from '@/lib/responseDraft';
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
  const [draft, setDraft] = useState<Draft>(NO_DRAFT);
  const queryClient = useQueryClient();

  // Here rather than in the sheet: the sheet can be closed while an answer is
  // on its way, and one opened again must still see it as sending (or as
  // failed) instead of offering to send it a second time.
  const respond = useMutation({
    mutationFn: ({ requestId, body }: { requestId: number; body: ResponseCreate }) =>
      api.respondToRequest(requestId, body),
    onSuccess: (_, { requestId }) => {
      hapticSuccess();
      // Marked at once, so the card cannot offer to answer again while the
      // lists come back.
      queryClient.setQueriesData<FeedRequest[]>(
        { queryKey: ['request-feed', 'list'] },
        (rows) =>
          rows?.map((row) => (row.id === requestId ? { ...row, responded: true } : row)),
      );
      // The request stays, now marked as answered and further down, and the
      // counts on the chips and in «Профиль» move: all of it is stale.
      void queryClient.invalidateQueries({ queryKey: ['request-feed'] });
      // Only if it is still this request on screen: by now the person may
      // have closed the sheet and opened another one.
      setAnswering((open) => (open?.id === requestId ? null : open));
      setDraft((kept) => (kept.requestId === requestId ? NO_DRAFT : kept));
    },
  });

  // `?request=<id>` is where the bot's message about a new request lands: that
  // request open to answer, once. Dropped from the URL after, so a reload or
  // a way back does not open it again. One already answered, or no longer in
  // the feed — closed, out of the list — leaves just the list.
  const [params, setParams] = useSearchParams();
  const linked = Number(params.get('request'));

  // The numbers on the chips, answered requests included as the lists are.
  const facets = useQuery({
    queryKey: ['request-feed', 'facets', true],
    queryFn: ({ signal }) => api.getFeedFacets(true, signal),
  });
  // Without them: what still waits, which picks the chip to open on. The
  // same query as «Профиль», so its number and this choice agree.
  const waiting = useQuery({
    queryKey: ['request-feed', 'facets', false],
    queryFn: ({ signal }) => api.getFeedFacets(false, signal),
  });
  // A linked request opens on «Все», since under «Мои услуги» it may not be
  // there to open. Otherwise the default, chosen once: worked out again on
  // every refetch, it would switch the list under someone who just answered.
  const [chosen, setChosen] = useState<FeedChip | null>(() => (linked ? ALL : null));
  const opening = waiting.data
    ? defaultChip(waiting.data.mine)
    : waiting.isError
      ? ALL
      : null;
  useEffect(() => {
    if (opening) setChosen((current) => current ?? opening);
  }, [opening]);
  const chip = chosen ?? opening;

  const query = chip ? feedQuery(chip) : null;
  const { data, isPending, isError, error } = useQuery({
    queryKey: ['request-feed', 'list', query],
    queryFn: ({ signal }) => api.getRequestFeed(query ?? feedQuery(ALL), signal),
    enabled: query !== null,
  });
  useEffect(() => {
    if (!linked || !data) return;
    const found = data.find((request) => request.id === linked);
    if (found && !found.responded) {
      setDraft((kept) =>
        kept.requestId === found.id ? kept : openDraft(found.id, found.suggested_price),
      );
      setAnswering(found);
    }
    const updated = new URLSearchParams(params);
    updated.delete('request');
    setParams(updated, { replace: true });
  }, [linked, data, params, setParams]);

  // 403 is not a failure here: it is the answer for someone who has no helper
  // profile, and the useful response is the invitation to make one.
  const forbidden = (failure: unknown) =>
    failure instanceof ApiError && failure.status === 403;
  if (forbidden(error) || forbidden(facets.error) || forbidden(waiting.error)) {
    return (
      <Empty
        title={<Trans>Сначала заполни профиль</Trans>}
        body={<Trans>Заявки видят те, кто может на них ответить.</Trans>}
      />
    );
  }

  const chips = facets.data ? feedChips(facets.data, chip) : [];

  return (
    <>
      {chips.length > 1 && chip ? (
        <>
          <div className={ui.feedChips}>
            {chips.map((option) => (
              <ChipView
                key={chipKey(option)}
                active={chipKey(option) === chipKey(chip)}
                pressed={chipKey(option) === chipKey(chip)}
                onClick={() => {
                  hapticSelection();
                  setChosen(option);
                }}
              >
                <ChipLabel chip={option} />
                <em className={ui.chipCount}>{option.count}</em>
              </ChipView>
            ))}
          </div>
          <div style={{ height: 14 }} />
        </>
      ) : null}

      {isPending ? (
        <SkeletonRows count={3} />
      ) : isError ? (
        <Empty title={<Trans>Не получилось загрузить</Trans>} />
      ) : data.length === 0 ? (
        chip?.kind === 'all' ? (
          <Empty
            title={<Trans>Пока никто ничего не просит</Trans>}
            body={
              <Trans>
                Здесь появятся заявки со всего каталога. Те, что по твоим услугам, будут
                выше.
              </Trans>
            }
          />
        ) : (
          <Empty title={<Trans>Под этот фильтр сейчас заявок нет</Trans>} />
        )
      ) : chip ? (
        feedSections(data, chip).map((section) => (
          <div key={section.heading ?? 'all'} className={ui.feedSection}>
            {section.heading ? (
              <div className={ui.feedSubhead}>
                <SectionHeading heading={section.heading} count={section.rows.length} />
              </div>
            ) : null}
            <Cards>
              {section.rows.map((request) => (
                <FeedCard
                  key={request.id}
                  request={request}
                  locale={i18n.locale}
                  onRespond={() => {
                    if (draft.requestId !== request.id) {
                      setDraft(openDraft(request.id, request.suggested_price));
                    }
                    setAnswering(request);
                  }}
                />
              ))}
            </Cards>
          </div>
        ))
      ) : null}

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

// The count is the row's to show; a chip held in state only names a filter.
const ALL: FeedChip = { kind: 'all', count: 0 };

function ChipLabel({ chip }: { chip: FeedChip }) {
  switch (chip.kind) {
    case 'mine':
      return <Trans>Мои услуги</Trans>;
    case 'all':
      return <Trans>Все</Trans>;
    case 'online':
      return <Trans>Онлайн</Trans>;
    case 'budget': {
      const amount = formatMoney(chip.amount);
      return <Trans>До {amount} Kč</Trans>;
    }
    default:
      return chip.name;
  }
}

function SectionHeading({
  heading,
  count,
}: {
  heading: 'mine' | 'others';
  count: number;
}) {
  return heading === 'mine' ? (
    <Trans>По твоим услугам · {count}</Trans>
  ) : (
    <Trans>Остальные · {count}</Trans>
  );
}

const NO_DRAFT: Draft = {
  requestId: null,
  message: '',
  price: '',
  unit: 'hour',
  suggested: null,
};

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
      ) : request.on_my_services === false ? (
        <Reason weak>
          <Trans>Не твоя услуга</Trans>
        </Reason>
      ) : null}

      <Actions>
        {/* Quiet: the list is a page of these, and a column of filled
            buttons reads as a wall rather than as a choice. The filled one
            is the send inside the sheet, where there is exactly one. */}
        {request.responded ? (
          <Action quiet sent onClick={() => {}}>
            <Trans>Отклик отправлен</Trans>
          </Action>
        ) : (
          <Action quiet onClick={onRespond}>
            <Trans>Откликнуться</Trans>
          </Action>
        )}
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
  const payload = responseDraft(draft.message, draft.price, draft.unit);
  // A tap or two instead of typing: each adds its sentence to the message.
  const starters = [
    t`Могу на этой неделе`,
    t`Первые 20 минут бесплатно`,
    t`Онлайн или лично`,
  ];

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
        <span className={ui.requestQuoteText}>{requestQuote(request)}</span>
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
            maxLength={MESSAGE_MAX}
            style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.4 }}
          />
        </div>
        <div className={ui.starters}>
          {starters.map((starter) => (
            <ChipView
              key={starter}
              onClick={() =>
                onDraft({ ...draft, message: withStarter(draft.message, starter) })
              }
            >
              {starter}
            </ChipView>
          ))}
        </div>

        <label className={ui.fieldLabel} htmlFor={priceId}>
          {/* «из анкеты» only while the field still holds the profile's
              price; changed or cleared, it is the person's own. */}
          {draft.suggested !== null && draft.price.trim() === draft.suggested ? (
            <Trans>
              Цена <PriceUnitLabel unit={draft.unit} />, Kč{' '}
              <span className={ui.fieldLabelNote}>из анкеты, можно изменить</span>
            </Trans>
          ) : (
            <Trans>
              Цена <PriceUnitLabel unit={draft.unit} />, Kč{' '}
              <span className={ui.fieldLabelNote}>необязательно</span>
            </Trans>
          )}
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
