import { Trans, useLingui } from '@lingui/react/macro';
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { type ReactNode, useState } from 'react';
import { useNavigate } from 'react-router';

import { Pick, Sheet } from '@/components/Sheet';
import {
  Action,
  Actions,
  Chips,
  ChipView,
  Hint,
  Label,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { useBrowserConsole } from '@/console/browserContext';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { FailureText } from '@/console/FailureText';
import { PingSheet } from '@/console/Pings';
import {
  consoleChanges,
  consoleChatsQuery,
  consoleSignalsQuery,
  consoleStatsQuery,
  spamCountQuery,
  spamQueueQuery,
} from '@/console/queries';
import css from '@/console/Spam.module.css';
import {
  ConsoleError,
  personName,
  type SpamPing,
  type SpamVerdict,
  utc,
} from '@/console/session';
import { awaitsAnswer, byDay, type PingFilters, type PingStatus } from '@/console/spam';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * What the ad detector caught, as a queue: each hit waits until a moderator
 * bans its author, calls it a false alarm or marks it done. The false alarms
 * stay listed, to tune the detector by.
 */
export default function ConsoleSpamPage() {
  return (
    <ConsoleGate>
      <div data-wide>
        <Title>
          <Trans>Реклама</Trans>
        </Title>
        <Spam />
      </div>
    </ConsoleGate>
  );
}

const PERIODS = [1, 7, 30, null] as const;

type Opened =
  | { kind: 'ping'; ping: SpamPing; ban: boolean }
  | { kind: 'chat' }
  | { kind: 'period' }
  | null;

function Spam() {
  const { t } = useLingui();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const inBrowser = useBrowserConsole();
  const [filters, setFilters] = useState<PingFilters>({
    status: 'unreviewed',
    chatId: null,
    days: null,
  });
  const [opened, setOpened] = useState<Opened>(null);
  const queue = useInfiniteQuery(spamQueueQuery(filters));
  const count = useQuery(spamCountQuery(filters));
  const chats = useQuery(consoleChatsQuery);

  // Held until the lists are read again, so the card answered keeps its
  // buttons off until it is gone: a second tap would only be refused.
  const reread = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ['console', 'spam'] }),
      queryClient.invalidateQueries({ queryKey: consoleStatsQuery.queryKey }),
      queryClient.invalidateQueries({ queryKey: consoleSignalsQuery.queryKey }),
    ]);
  const review = useMutation({
    mutationFn: ({
      ping,
      verdict,
    }: {
      ping: SpamPing;
      verdict: Exclude<SpamVerdict, 'ad'>;
    }) => consoleChanges.reviewPing(ping.id, verdict),
    onSuccess: reread,
    // Answered by somebody else meanwhile: show it as it now is.
    onError: (error) =>
      error instanceof ConsoleError && error.status === 409 ? reread() : undefined,
  });

  const filter = (change: Partial<PingFilters>) => {
    hapticSelection();
    setFilters((current) => ({ ...current, ...change }));
    setOpened(null);
  };
  const periodName = (days: number | null) =>
    days === 1
      ? t`За сутки`
      : days === 7
        ? t`За 7 дней`
        : days === 30
          ? t`За 30 дней`
          : t`За всё время`;
  const chatName = (id: number) =>
    chats.data?.find((chat) => chat.id === id)?.title ?? String(id);
  const unreviewed = count.data?.count;
  const pings = queue.data?.pages.flat() ?? [];

  const statusChip = (status: PingStatus, label: ReactNode) => (
    <ChipView active={filters.status === status} onClick={() => filter({ status })}>
      {label}
    </ChipView>
  );

  return (
    <>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>Что поймал детектор. Разобранное уходит из очереди.</Trans>
        </Sub>
      </div>
      {/* In a browser the status and the chat and period chips share a line. */}
      <div className={inBrowser ? css.filters : ui.column} style={{ marginTop: 12 }}>
        <Chips>
          {statusChip(
            'unreviewed',
            unreviewed === undefined ? (
              <Trans>Не разобрано</Trans>
            ) : (
              <Trans>Не разобрано · {unreviewed}</Trans>
            ),
          )}
          {statusChip('all', <Trans>Все</Trans>)}
          {statusChip('not_ad', <Trans>Не реклама</Trans>)}
        </Chips>
        <Chips>
          <ChipView
            active={filters.chatId !== null}
            onClick={() => setOpened({ kind: 'chat' })}
          >
            {filters.chatId === null ? (
              <Trans>Чат: все ▾</Trans>
            ) : (
              <Trans>Чат: {chatName(filters.chatId)} ▾</Trans>
            )}
          </ChipView>
          <ChipView
            active={filters.days !== null}
            onClick={() => setOpened({ kind: 'period' })}
          >
            {periodName(filters.days)} ▾
          </ChipView>
        </Chips>
      </div>

      {review.error ? (
        <Hint>
          {review.error instanceof ConsoleError && review.error.status === 409 ? (
            <Trans>Этот случай уже разобрал другой модератор.</Trans>
          ) : (
            <FailureText error={review.error} />
          )}
        </Hint>
      ) : null}
      {queue.isPending ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={4} />
        </div>
      ) : queue.error ? (
        <div style={{ marginTop: 16 }}>
          <ConsoleFailure error={queue.error} retry={() => void queue.refetch()} />
        </div>
      ) : pings.length === 0 ? (
        <div style={{ marginTop: 16 }}>
          <Hint>
            {filters.status === 'unreviewed' ? (
              <Trans>Очередь пуста: всё разобрано.</Trans>
            ) : filters.status === 'not_ad' ? (
              <Trans>Отметок «не реклама» нет.</Trans>
            ) : (
              <Trans>Детектор ничего не находил.</Trans>
            )}
          </Hint>
        </div>
      ) : (
        <>
          {byDay(pings).map((group) => (
            <div key={group.day}>
              <Label aside={group.pings.length}>
                <DayName day={group.day} />
              </Label>
              <div className={ui.column}>
                {group.pings.map((ping) => (
                  <PingCard
                    key={ping.id}
                    ping={ping}
                    showChat={filters.chatId === null}
                    busy={review.isPending && review.variables?.ping.id === ping.id}
                    onOpen={() => setOpened({ kind: 'ping', ping, ban: false })}
                    onBan={() => setOpened({ kind: 'ping', ping, ban: true })}
                    onReview={(verdict: Exclude<SpamVerdict, 'ad'>) => {
                      hapticSelection();
                      review.mutate({ ping, verdict });
                    }}
                  />
                ))}
              </div>
            </div>
          ))}
          {queue.hasNextPage ? (
            <div style={{ marginTop: 12 }}>
              <Actions>
                <Action
                  quiet
                  disabled={queue.isFetchingNextPage}
                  onClick={() => void queue.fetchNextPage()}
                >
                  <Trans>Показать ещё</Trans>
                </Action>
              </Actions>
            </div>
          ) : null}
        </>
      )}

      {opened?.kind === 'ping' ? (
        <PingSheet
          key={opened.ping.id}
          ping={opened.ping}
          banFirst={opened.ban}
          onClose={() => setOpened(null)}
          // A chat the bot never stored has no screen to open.
          onOpenChat={
            opened.ping.chat_title === null
              ? undefined
              : () => navigate(`/console/chats/${opened.ping.chat_id}`)
          }
        />
      ) : null}
      {opened?.kind === 'chat' ? (
        <Sheet title={t`Чат`} closeLabel={t`Отмена`} onClose={() => setOpened(null)}>
          <div className={ui.sheetList}>
            <Pick
              name={<Trans>Все чаты</Trans>}
              selected={filters.chatId === null}
              onClick={() => filter({ chatId: null })}
            />
            {[...(chats.data ?? [])]
              .sort((a, b) => (a.title ?? '').localeCompare(b.title ?? ''))
              .map((chat) => (
                <Pick
                  key={chat.id}
                  name={chat.title ?? String(chat.id)}
                  selected={filters.chatId === chat.id}
                  onClick={() => filter({ chatId: chat.id })}
                />
              ))}
          </div>
        </Sheet>
      ) : null}
      {opened?.kind === 'period' ? (
        <Sheet title={t`Период`} closeLabel={t`Отмена`} onClose={() => setOpened(null)}>
          {PERIODS.map((days) => (
            <Pick
              key={days ?? 'all'}
              name={periodName(days)}
              selected={filters.days === days}
              onClick={() => filter({ days })}
            />
          ))}
        </Sheet>
      ) : null}
    </>
  );
}

function DayName({ day }: { day: string }) {
  const { i18n } = useLingui();
  if (day === 'today') return <Trans>Сегодня</Trans>;
  if (day === 'yesterday') return <Trans>Вчера</Trans>;
  const date = `${day}T12:00:00`;
  // The year only where it is not this one, as a calendar writes it.
  const thisYear = day.startsWith(String(new Date().getFullYear()));
  return (
    <>
      {i18n.date(date, {
        day: 'numeric',
        month: 'long',
        ...(thisYear ? {} : { year: 'numeric' }),
      })}
    </>
  );
}

/**
 * One hit in the queue: where and who, what they wrote, and the three
 * answers. An answered hit says what the answer was instead.
 */
function PingCard({
  ping,
  showChat,
  busy,
  onOpen,
  onBan,
  onReview,
}: {
  ping: SpamPing;
  showChat: boolean;
  busy: boolean;
  onOpen: () => void;
  onBan: () => void;
  onReview: (verdict: Exclude<SpamVerdict, 'ad'>) => void;
}) {
  const { i18n } = useLingui();
  const time = i18n.date(utc(ping.detected_at), { hour: '2-digit', minute: '2-digit' });
  return (
    <div className={ui.pingCard}>
      <button
        type="button"
        className={`${ui.pingCardBody} ${ui.pressable}`}
        onClick={() => {
          hapticSelection();
          onOpen();
        }}
      >
        <span className={ui.pingCardTop}>
          <span>
            {showChat ? (
              <>
                <b>{ping.chat_title ?? ping.chat_id}</b>
                {' · '}
              </>
            ) : null}
            {personName(ping)}
          </span>
          <span>{time}</span>
        </span>
        <span className={ui.pingCardText}>{ping.snippet ?? ping.matches.join(', ')}</span>
      </button>
      {awaitsAnswer(ping) ? (
        <Actions>
          <Action disabled={busy} onClick={onBan}>
            <Trans>Забанить…</Trans>
          </Action>
          <Action quiet disabled={busy} onClick={() => onReview('not_ad')}>
            <Trans>Не реклама</Trans>
          </Action>
          <Action quiet disabled={busy} onClick={() => onReview('done')}>
            <Trans>Разобрано</Trans>
          </Action>
        </Actions>
      ) : (
        <span className={ui.pingCardVerdict}>
          {ping.verdict === 'not_ad' ? (
            <Trans>Не реклама</Trans>
          ) : ping.verdict === 'done' ? (
            <Trans>Разобрано</Trans>
          ) : (
            <Trans>Автор забанен</Trans>
          )}
        </span>
      )}
    </div>
  );
}
