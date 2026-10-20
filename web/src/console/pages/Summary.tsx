import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { type ReactNode, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  BagIcon,
  ChatIcon,
  DocumentIcon,
  PersonIcon,
  ShieldIcon,
  TargetIcon,
} from '@/components/icons';
import {
  Chevron,
  Count,
  Hint,
  Label,
  Row,
  Rows,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { dayCells, memberChange, signed } from '@/console/activity';
import { useBrowserConsole } from '@/console/browserContext';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import {
  adminCatalogQuery,
  adminPartnersQuery,
  audienceSummaryQuery,
  blockedQuery,
  consoleChatsQuery,
  consoleStatsQuery,
} from '@/console/queries';
import { type AttentionKey, attention, type BusyChat } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * The console's first screen: the day's numbers, what needs a look, where the
 * chats are busy, then its sections.
 */
export default function ConsoleSummaryPage() {
  return (
    <ConsoleGate>
      <Title>
        <Trans>Консоль</Trans>
      </Title>
      <Summary />
    </ConsoleGate>
  );
}

function Summary() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  // Read again every minute while it is open: it says how fresh it is.
  // Not after a failure: a stale sign-in would be sent again every minute.
  const stats = useQuery({
    ...consoleStatsQuery,
    refetchInterval: (query) => (query.state.status === 'error' ? false : 60_000),
  });
  const chats = useQuery(consoleChatsQuery);
  // The catalog's API takes a Telegram signature only, which a browser does not have.
  const inBrowser = useBrowserConsole();
  const catalog = useQuery({ ...adminCatalogQuery, enabled: !inBrowser });
  const partners = useQuery({ ...adminPartnersQuery, enabled: !inBrowser });
  const blocked = useQuery(blockedQuery);
  const audience = useQuery(audienceSummaryQuery);

  const open = (path: string) => {
    hapticSelection();
    navigate(path);
  };

  // Each backend answers for itself: webapi refusing must not hide what the
  // catalog said, and the other way round.
  const webapiError = stats.error ?? chats.error;
  const loading =
    (!inBrowser && catalog.isPending) ||
    (!webapiError && (stats.isPending || chats.isPending));
  const items = attention({
    adsUnreviewed: stats.data?.spam_pings.unreviewed ?? 0,
    chats: chats.data ?? [],
    requestsUnanswered: catalog.data?.counts.unanswered ?? 0,
  });
  const approved = chats.data?.filter(
    (chat) => chat.resource_status === 'approved',
  ).length;
  const activePlacements = partners.data?.filter((row) => row.is_active).length;

  const attentionRow: Record<AttentionKey, (count: number) => ReactNode> = {
    ads: (count) => (
      <Row
        key="ads"
        leading={
          <Tile tone={1}>
            <ShieldIcon size={19} />
          </Tile>
        }
        title={<Trans>Реклама не разобрана</Trans>}
        hint={<Trans>детектор, все чаты</Trans>}
        trailing={<Count>{count}</Count>}
        onClick={() => open('/console/spam')}
      />
    ),
    review: (count) => (
      <Row
        key="review"
        leading={
          <Tile tone={3}>
            <ChatIcon size={19} />
          </Tile>
        }
        title={<Trans>Чаты на проверке</Trans>}
        hint={<Trans>бот в них есть, но они не одобрены</Trans>}
        trailing={<Count>{count}</Count>}
        onClick={() => open('/console/chats?status=discovered')}
      />
    ),
    requests: (count) => (
      <Row
        key="requests"
        leading={
          <Tile tone={2}>
            <TargetIcon size={19} />
          </Tile>
        }
        title={<Trans>Заявки без откликов</Trans>}
        hint={<Trans>открытые, срок не вышел</Trans>}
        trailing={<Count>{count}</Count>}
        onClick={() => open('/console/catalog')}
      />
    ),
  };

  return (
    <>
      <div style={{ marginTop: 6 }}>
        <Sub>
          {stats.dataUpdatedAt ? (
            <Updated at={stats.dataUpdatedAt} />
          ) : (
            <Trans>Что происходит в чатах и в каталоге.</Trans>
          )}
        </Sub>
      </div>

      {stats.data || catalog.data ? (
        <div className={ui.summaryTiles}>
          {stats.data ? <MembersTile stats={stats.data.members_delta} /> : null}
          {audience.data ? (
            <div className={ui.summaryTile} data-tone="0">
              <span>
                <Trans>Аудитория за неделю</Trans>
              </span>
              <b>+{i18n.number(audience.data.new_this_week)}</b>
              <small>
                <Trans>всего {i18n.number(audience.data.total)}</Trans>
              </small>
            </div>
          ) : null}
          {stats.data ? (
            <div className={ui.summaryTile} data-tone="1">
              <span>
                <Trans>Реклама за сутки</Trans>
              </span>
              <b>{stats.data.spam_pings.count_24h}</b>
              <small>
                <Trans>{stats.data.spam_pings.unreviewed} всего не разобрано</Trans>
              </small>
            </div>
          ) : null}
          {catalog.data ? (
            <div className={ui.summaryTile} data-tone="2">
              <span>
                <Trans>Каталог за неделю</Trans>
              </span>
              <b>{catalog.data.counts.profiles_week}</b>
              <small>
                <Plural
                  value={catalog.data.counts.profiles_week}
                  one="новая анкета"
                  few="новые анкеты"
                  many="новых анкет"
                  other="новых анкет"
                />
              </small>
            </div>
          ) : null}
        </div>
      ) : null}

      <Label
        aside={
          loading || !items.length
            ? null
            : items.reduce((sum, item) => sum + item.count, 0)
        }
      >
        <Trans>Требует внимания</Trans>
      </Label>
      {loading ? (
        <SkeletonRows count={2} />
      ) : (
        <div className={ui.column}>
          {webapiError ? (
            <ConsoleFailure
              error={webapiError}
              retry={() => {
                void stats.refetch();
                void chats.refetch();
              }}
            />
          ) : null}
          {catalog.error ? (
            <ConsoleFailure error={catalog.error} retry={() => void catalog.refetch()} />
          ) : null}
          {items.length > 0 ? (
            <Rows>{items.map((item) => attentionRow[item.key](item.count))}</Rows>
          ) : !webapiError && !catalog.error ? (
            <Hint>
              <Trans>Сейчас ничего не ждёт.</Trans>
            </Hint>
          ) : null}
        </div>
      )}

      {stats.data ? (
        <>
          <Label aside={<Trans>сутки</Trans>}>
            <Trans>Самые живые чаты, сообщения по часам</Trans>
          </Label>
          <BusyChats chats={stats.data.chat_heatmap.slice(0, 5)} />
        </>
      ) : null}

      <Label>
        <Trans>Разделы</Trans>
      </Label>
      <Rows>
        <Row
          leading={
            <Tile tone={3}>
              <ChatIcon size={19} />
            </Tile>
          }
          title={<Trans>Чаты</Trans>}
          hint={
            chats.data ? (
              <Trans>
                <Plural
                  value={chats.data.length}
                  one="# чат"
                  few="# чата"
                  many="# чатов"
                  other="# чата"
                />{' '}
                · одобрено {approved}
              </Trans>
            ) : (
              <Trans>иерархия, защита, модерация</Trans>
            )
          }
          trailing={<Chevron />}
          onClick={() => open('/console/chats')}
        />
        <Row
          leading={
            <Tile tone={2}>
              <PersonIcon size={19} />
            </Tile>
          }
          title={<Trans>Аудитория</Trans>}
          hint={<Trans>кто пользовался ботами и Mini App</Trans>}
          trailing={<Chevron />}
          onClick={() => open('/console/audience')}
        />
        {inBrowser ? null : (
          <>
            <Row
              leading={
                <Tile tone={0}>
                  <DocumentIcon size={19} />
                </Tile>
              }
              title={<Trans>Каталог</Trans>}
              hint={<Trans>анкеты, заявки, поиски без ответа</Trans>}
              trailing={<Chevron />}
              onClick={() => open('/console/catalog')}
            />
            <Row
              leading={
                <Tile tone={2}>
                  <BagIcon size={19} />
                </Tile>
              }
              title={<Trans>Партнёры</Trans>}
              hint={
                activePlacements !== undefined ? (
                  <Trans>
                    <Plural
                      value={activePlacements}
                      one="# карточка"
                      few="# карточки"
                      many="# карточек"
                      other="# карточки"
                    />{' '}
                    · показы и клики
                  </Trans>
                ) : (
                  <Trans>показы и клики</Trans>
                )
              }
              trailing={<Chevron />}
              onClick={() => open('/console/partners')}
            />
          </>
        )}
        <Row
          leading={
            <Tile tone={1}>
              <ShieldIcon size={19} />
            </Tile>
          }
          title={<Trans>Реклама</Trans>}
          hint={
            stats.data ? (
              <Trans>
                {stats.data.spam_pings.count_24h} за сутки ·{' '}
                {stats.data.spam_pings.count_7d} за неделю
              </Trans>
            ) : (
              <Trans>что поймал детектор</Trans>
            )
          }
          trailing={<Chevron />}
          onClick={() => open('/console/spam')}
        />
        <Row
          leading={
            <Tile tone={4}>
              <ShieldIcon size={19} />
            </Tile>
          }
          title={<Trans>Чёрный список</Trans>}
          hint={
            blocked.data ? (
              <Plural
                value={blocked.data.length}
                one="# человек"
                few="# человека"
                many="# человек"
                other="# человека"
              />
            ) : (
              <Trans>забанены во всех чатах</Trans>
            )
          }
          trailing={<Chevron />}
          onClick={() => open('/console/blacklist')}
        />
        <Row
          leading={
            <Tile tone={5}>
              <ShieldIcon size={19} />
            </Tile>
          }
          title={<Trans>Система</Trans>}
          hint={<Trans>где выполнен вход, настройки</Trans>}
          trailing={<Chevron />}
          onClick={() => open('/console/system')}
        />
      </Rows>
    </>
  );
}

/** How long ago the numbers were read, kept current while the screen is open. */
function Updated({ at }: { at: number }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const minutes = Math.max(0, Math.floor((now - at) / 60_000));
  return minutes === 0 ? (
    <Trans>Обновлено только что</Trans>
  ) : (
    <Trans>Обновлено {minutes} мин назад</Trans>
  );
}

function MembersTile({ stats }: { stats: Parameters<typeof memberChange>[0] }) {
  const { i18n } = useLingui();
  const { day, week } = memberChange(stats);
  const write = (n: number) => signed(n, (abs) => i18n.number(abs));
  return (
    <div className={ui.summaryTile} data-tone="3">
      <span>
        <Trans>Участники за сутки</Trans>
      </span>
      <b>{day === null ? '—' : write(day)}</b>
      <small>
        {week === null ? (
          <Trans>за 7 дней — пока не с чем сравнить</Trans>
        ) : (
          <Trans>за 7 дней {write(week)}</Trans>
        )}
      </small>
    </div>
  );
}

/**
 * The busiest chats of the last day, each as eight three-hour cells in the
 * reader's time. One scale for all of them, so a darker cell is busier
 * whichever chat it is in.
 */
function BusyChats({ chats }: { chats: BusyChat[] }) {
  const { t } = useLingui();
  if (chats.length === 0) {
    return (
      <Hint>
        <Trans>За сутки бот не видел сообщений.</Trans>
      </Hint>
    );
  }
  const offset = -new Date().getTimezoneOffset();
  const rows = chats.map((chat) => ({ chat, cells: dayCells(chat.hours, offset) }));
  const max = Math.max(1, ...rows.flatMap((row) => row.cells));
  return (
    <div
      className={ui.busyChats}
      role="img"
      aria-label={t`Сообщения за сутки по часам: ${chats
        .map((chat) => `${chat.title ?? chat.chat_id} — ${chat.total_messages}`)
        .join(', ')}`}
    >
      {rows.map(({ chat, cells }) => (
        <div key={chat.chat_id} className={ui.busyChatRow}>
          <span className={ui.busyChatName}>{chat.title ?? chat.chat_id}</span>
          {cells.map((count, cell) => (
            <span
              // biome-ignore lint/suspicious/noArrayIndexKey: the hours are the identity.
              key={cell}
              className={ui.heatmapCell}
              style={{ opacity: count ? 0.18 + 0.82 * (count / max) : 1 }}
              data-empty={count === 0 || undefined}
            />
          ))}
        </div>
      ))}
      <div className={ui.busyChatRow}>
        <span />
        {[0, 6, 12, 18].map((hour) => (
          <span key={hour} className={ui.heatmapHour} style={{ gridColumn: `span 2` }}>
            {hour}
          </span>
        ))}
      </div>
    </div>
  );
}
