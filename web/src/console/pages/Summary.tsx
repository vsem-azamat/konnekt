import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { Fragment, type ReactNode, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  BagIcon,
  BlockIcon,
  ChatIcon,
  DocumentIcon,
  PeopleIcon,
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
import type { AudienceSummary } from '@/console/audience';
import { useBrowserConsole } from '@/console/browserContext';
import table from '@/console/ChatTable.module.css';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import {
  adminCatalogQuery,
  adminPartnersQuery,
  audienceSummaryQuery,
  blockedQuery,
  consoleChatsQuery,
  consoleSignalsQuery,
  consoleStatsQuery,
  consoleSystemQuery,
} from '@/console/queries';
import css from '@/console/Summary.module.css';
import { type AttentionKey, attention, type BusyChat } from '@/console/session';
import {
  elapsed,
  minutesUntil,
  type PendingActionSignal,
  type WaveSignal,
} from '@/console/signals';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * The console's first screen: the day's numbers, what needs a look, where the
 * chats are busy, then its sections.
 */
export default function ConsoleSummaryPage() {
  // In a browser the menu names this screen Обзор; the Mini App has no menu.
  const inBrowser = useBrowserConsole();
  return (
    <ConsoleGate wide>
      <Title>{inBrowser ? <Trans>Обзор</Trans> : <Trans>Консоль</Trans>}</Title>
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
  const catalog = useQuery(adminCatalogQuery);
  const partners = useQuery(adminPartnersQuery);
  const blocked = useQuery(blockedQuery);
  const audience = useQuery(audienceSummaryQuery);
  // The browser's summary also lists the waves and the proposals, and says
  // whether the console's bot can act; the menu reads the signals already.
  const inBrowser = useBrowserConsole();
  const signals = useQuery({ ...consoleSignalsQuery, enabled: inBrowser });
  const system = useQuery({ ...consoleSystemQuery, enabled: inBrowser });

  const open = (path: string) => {
    hapticSelection();
    navigate(path);
  };

  // Each backend answers for itself: webapi refusing must not hide what the
  // catalog said, and the other way round.
  // Signals are asked for only in a browser; a disabled query stays pending.
  const webapiError = stats.error ?? chats.error ?? signals.error;
  const loading =
    catalog.isPending ||
    (!webapiError &&
      (stats.isPending || chats.isPending || (inBrowser && signals.isPending)));
  const items = attention({
    adsUnreviewed: stats.data?.spam_pings.unreviewed ?? 0,
    chats: chats.data ?? [],
    profilesToReview: inBrowser ? catalog.data?.counts.profiles_to_review : undefined,
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
    profiles: (count) => (
      <Row
        key="profiles"
        leading={
          <Tile tone={2}>
            <PersonIcon size={19} />
          </Tile>
        }
        title={<Trans>Новые анкеты</Trans>}
        hint={<Trans>каталог</Trans>}
        trailing={<Count>{count}</Count>}
        onClick={() => open('/console/catalog')}
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

  // Each wave and proposal on a row of its own, above the queues, as the
  // Сигналы screen puts them.
  const waiting = inBrowser
    ? [
        ...(signals.data?.waves ?? []).map((wave) => (
          <WaveRow
            key={`wave-${wave.id}`}
            wave={wave}
            onClick={() => open('/console/signals')}
          />
        )),
        ...(signals.data?.pending_actions ?? []).map((proposal) => (
          <ProposalRow
            key={`proposal-${proposal.id}`}
            proposal={proposal}
            onClick={() => open('/console/signals')}
          />
        )),
      ]
    : [];

  const updated = (
    <div style={{ marginTop: 6 }}>
      <Sub>
        {stats.dataUpdatedAt ? (
          <Updated at={stats.dataUpdatedAt} />
        ) : (
          <Trans>Что происходит в чатах и в каталоге.</Trans>
        )}
      </Sub>
    </div>
  );

  const tiles = (
    <>
      {stats.data || catalog.data ? (
        <div className={inBrowser ? css.kpis : ui.summaryTiles}>
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
    </>
  );

  const needs = (
    <>
      <Label
        aside={
          loading || !(items.length + waiting.length)
            ? null
            : items.reduce((sum, item) => sum + item.count, waiting.length)
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
                if (inBrowser) void signals.refetch();
              }}
            />
          ) : null}
          {catalog.error ? (
            <ConsoleFailure error={catalog.error} retry={() => void catalog.refetch()} />
          ) : null}
          {items.length + waiting.length > 0 ? (
            <Rows>
              {waiting}
              {items.map((item) => attentionRow[item.key](item.count))}
            </Rows>
          ) : !webapiError && !catalog.error ? (
            <Hint>
              <Trans>Сейчас ничего не ждёт.</Trans>
            </Hint>
          ) : null}
        </div>
      )}
    </>
  );

  if (inBrowser) {
    return (
      <>
        {updated}
        {tiles}
        <div className={css.grid}>
          <div>{needs}</div>
          <div className={css.column}>
            <section className={css.card}>
              <Bots
                audience={audience.data}
                error={audience.error}
                retry={() => void audience.refetch()}
                ready={system.data?.publish_bot_ready}
              />
            </section>
            {stats.data ? (
              <section className={css.card}>
                <Label aside={<Trans>сутки</Trans>}>
                  <Trans>Самые живые чаты, сообщения по часам</Trans>
                </Label>
                <HourlyChats chats={stats.data.chat_heatmap.slice(0, 5)} />
              </section>
            ) : null}
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      {updated}

      {tiles}

      {needs}

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

/** A wave on the summary: where, how many wait, and whether the captcha is paused. */
function WaveRow({ wave, onClick }: { wave: WaveSignal; onClick: () => void }) {
  const title = wave.chat_title ?? String(wave.chat_id);
  const surge = elapsed(wave.last_surge_at);
  const ago = surge.unit === 'minutes' ? surge.count : 0;
  const hoursAgo = surge.unit === 'hours' ? surge.count : 0;
  const held = (
    <Plural
      value={wave.held}
      one="# заявка ждёт"
      few="# заявки ждут"
      many="# заявок ждут"
      other="# заявки ждут"
    />
  );
  return (
    <Row
      leading={
        <Tile tone={4}>
          <PeopleIcon size={19} />
        </Tile>
      }
      title={<Trans>Набег на {title}</Trans>}
      hint={
        surge.unit === 'now' ? (
          <Trans>{held} · только что</Trans>
        ) : surge.unit === 'minutes' ? (
          <Trans>
            {held} · {ago} мин назад
          </Trans>
        ) : (
          <Trans>
            {held} · {hoursAgo} ч назад
          </Trans>
        )
      }
      trailing={
        wave.paused ? (
          <span className={`${table.pill} ${table.warn}`}>
            <Trans>Капча на паузе</Trans>
          </span>
        ) : (
          <Chevron />
        )
      }
      onClick={onClick}
    />
  );
}

/** A ban proposed through MCP on the summary: whom, and how long it waits. */
function ProposalRow({
  proposal,
  onClick,
}: {
  proposal: PendingActionSignal;
  onClick: () => void;
}) {
  const who =
    proposal.target_name ??
    (proposal.target_username
      ? `@${proposal.target_username}`
      : String(proposal.target_user_id));
  const chat = proposal.chat_title ?? String(proposal.chat_id);
  const left = minutesUntil(proposal.expires_at);
  return (
    <Row
      leading={
        <Tile tone={1}>
          <BlockIcon size={19} />
        </Tile>
      }
      title={
        proposal.action === 'blacklist' ? (
          <Trans>Чёрный список: {who}</Trans>
        ) : proposal.chat_id === null ? (
          <Trans>Бан {who} во всех чатах</Trans>
        ) : (
          <Trans>
            Бан {who} в {chat}
          </Trans>
        )
      }
      hint={<Trans>предложено через MCP · истекает через {left} мин</Trans>}
      trailing={
        <span className={`${table.pill} ${table.warn}`}>
          <Trans>Ждёт нажатия</Trans>
        </span>
      }
      onClick={onClick}
    />
  );
}

/**
 * Who each bot can reach. The main bot by whether it may write (the
 * announcements' measure); the others by the people they met first, as the
 * Audience screen counts them; the ads bot by the people who wrote to it.
 */
function Bots({
  audience,
  error,
  retry,
  ready,
}: {
  audience: AudienceSummary | undefined;
  error: Error | null;
  retry: () => void;
  ready: boolean | undefined;
}) {
  const { i18n } = useLingui();
  const n = (value: number) => i18n.number(value);
  return (
    <>
      <Label
        aside={
          ready === undefined ? null : ready ? (
            <Trans>бот для действий консоли: готов</Trans>
          ) : (
            <Trans>бот для действий консоли: не настроен</Trans>
          )
        }
      >
        <Trans>Боты</Trans>
      </Label>
      {audience ? (
        <div className={css.tableWrap}>
          <table className={css.table}>
            <thead>
              <tr>
                <th>
                  <Trans>Бот</Trans>
                </th>
                <th className={css.num}>
                  <Trans>Число</Trans>
                </th>
                <th>
                  <Trans>Что считаем</Trans>
                </th>
                <th>
                  <Trans>Заблокировали</Trans>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <b>
                    <Trans>Основной бот</Trans>
                  </b>
                  <small>
                    <Trans>бот и Mini App</Trans>
                  </small>
                </td>
                <td className={css.num}>{n(audience.reach.reachable)}</td>
                <td>
                  <Trans>могут получить сообщение</Trans>
                </td>
                <td>{n(audience.reach.blocked)}</td>
              </tr>
              <tr>
                <td>
                  <b>
                    <Trans>Бот связи</Trans>
                  </b>
                  <small>
                    <Trans>«Написать нам» и реклама</Trans>
                  </small>
                </td>
                <td className={css.num}>{n(audience.first_touch.contact_bot ?? 0)}</td>
                <td>
                  <Trans>
                    первых касаний; диалогов о рекламе: {n(audience.ads_conversations)}
                  </Trans>
                </td>
                <td>{n(audience.contact_bot_blocked)}</td>
              </tr>
              <tr>
                <td>
                  <b>
                    <Trans>Старые боты</Trans>
                  </b>
                  <small>
                    <Trans>переехавшие подписчики</Trans>
                  </small>
                </td>
                <td className={css.num}>{n(audience.first_touch.moved_bot ?? 0)}</td>
                <td>
                  <Trans>первых касаний</Trans>
                </td>
                <td>—</td>
              </tr>
            </tbody>
          </table>
        </div>
      ) : error ? (
        <ConsoleFailure error={error} retry={retry} />
      ) : (
        <SkeletonRows count={2} />
      )}
    </>
  );
}

/**
 * The busiest chats of the last day by the hour, with room for all 24 of
 * them, and each chat's total. One scale for all, as in BusyChats.
 */
function HourlyChats({ chats }: { chats: BusyChat[] }) {
  const { t, i18n } = useLingui();
  if (chats.length === 0) {
    return (
      <Hint>
        <Trans>За сутки бот не видел сообщений.</Trans>
      </Hint>
    );
  }
  const offset = -new Date().getTimezoneOffset();
  const rows = chats.map((chat) => ({ chat, cells: dayCells(chat.hours, offset, 1) }));
  const max = Math.max(1, ...rows.flatMap((row) => row.cells));
  return (
    <div
      className={css.heatmap}
      role="img"
      aria-label={t`Сообщения за сутки по часам: ${chats
        .map((chat) => `${chat.title ?? chat.chat_id} — ${chat.total_messages}`)
        .join(', ')}`}
    >
      {rows.map(({ chat, cells }) => (
        <Fragment key={chat.chat_id}>
          <span className={css.heatName}>{chat.title ?? chat.chat_id}</span>
          <span className={css.heat}>
            {cells.map((count, hour) => (
              <span
                // biome-ignore lint/suspicious/noArrayIndexKey: the hours are the identity.
                key={hour}
                style={count ? { opacity: 0.18 + 0.82 * (count / max) } : undefined}
                data-empty={count === 0 || undefined}
              />
            ))}
          </span>
          <span className={css.num}>{i18n.number(chat.total_messages)}</span>
        </Fragment>
      ))}
      <span />
      <span className={css.hours}>
        {[0, 6, 12, 18].map((hour) => (
          <span key={hour}>{hour}</span>
        ))}
      </span>
      <span />
    </div>
  );
}
