import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { Fragment, type ReactNode, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  BagIcon,
  BellIcon,
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
import { useDay } from '@/console/AudienceCharts';
import { dayCells, memberChange, memberTrend, signed } from '@/console/activity';
import type { AudienceOverview } from '@/console/audience';
import { useBrowserConsole } from '@/console/browserContext';
import table from '@/console/ChatTable.module.css';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import {
  adminCatalogQuery,
  adminPartnersQuery,
  audienceOverviewQuery,
  blockedQuery,
  consoleChatsQuery,
  consoleSignalsQuery,
  consoleStatsQuery,
  consoleSystemQuery,
  everyMinute,
} from '@/console/queries';
import css from '@/console/Summary.module.css';
import {
  type AttentionKey,
  attention,
  type BusyChat,
  type HomeStats,
} from '@/console/session';
import { elapsed, menuCounts, type WaveSignal } from '@/console/signals';
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
  // Read again every minute while it is open: it says how fresh it is.
  const stats = useQuery({ ...consoleStatsQuery, refetchInterval: everyMinute });
  const chats = useQuery(consoleChatsQuery);
  const catalog = useQuery(adminCatalogQuery);
  const partners = useQuery(adminPartnersQuery);
  const blocked = useQuery(blockedQuery);
  const audience = useQuery(audienceOverviewQuery);
  // The waves, and whether the console's bot can act: the
  // same in both layouts. A browser's menu reads the signals too.
  const inBrowser = useBrowserConsole();
  // Polled here too: the Mini App has no menu to keep it fresh.
  const signals = useQuery({ ...consoleSignalsQuery, refetchInterval: everyMinute });
  const system = useQuery(consoleSystemQuery);
  // What the browser's menu counts, on the summary's sections in the Mini App.
  const counts = menuCounts(signals.data, catalog.data?.counts);

  const open = (path: string) => {
    hapticSelection();
    navigate(path);
  };

  // Each backend answers for itself: webapi refusing must not hide what the
  // catalog said, and the other way round.
  const webapiError = stats.error ?? chats.error ?? signals.error;
  const loading =
    catalog.isPending ||
    (!webapiError && (stats.isPending || chats.isPending || signals.isPending));
  const items = attention({
    adsUnreviewed: stats.data?.spam_pings.unreviewed ?? 0,
    chats: chats.data ?? [],
    profilesToReview: catalog.data?.counts.profiles_to_review,
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
        onClick={() => open('/console/chats?tab=decide')}
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

  // Each wave on a row of its own, above the queues, as the
  // Сигналы screen puts them.
  const waiting = [
    ...(signals.data?.waves ?? []).map((wave) => (
      <WaveRow
        key={`wave-${wave.id}`}
        wave={wave}
        onClick={() => open('/console/signals')}
      />
    )),
  ];

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
          {stats.data ? <MembersTile stats={stats.data} /> : null}
          {audience.data ? <CameTile came={audience.data.came} /> : null}
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
                void signals.refetch();
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

  const bots = (
    <Bots
      audience={audience.data}
      error={audience.error}
      retry={() => void audience.refetch()}
      ready={system.data?.publish_bot_ready}
      table={inBrowser}
      more={() => open('/console/audience')}
    />
  );

  if (inBrowser) {
    return (
      <>
        {updated}
        {tiles}
        <div className={css.grid}>
          <div>{needs}</div>
          <div className={css.column}>
            <section className={css.card}>{bots}</section>
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

      {bots}

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
            <Tile tone={1}>
              <BellIcon size={19} />
            </Tile>
          }
          title={<Trans>Сигналы</Trans>}
          hint={<Trans>набеги заявок и предложенные баны</Trans>}
          trailing={<Waiting count={counts.signals} />}
          onClick={() => open('/console/signals')}
        />
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
          trailing={<Waiting count={counts.chats} />}
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
          trailing={<Waiting count={counts.catalog} />}
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
          trailing={<Waiting count={counts.spam} />}
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

/** A section's row ends in what waits there, as a browser's menu counts it. */
function Waiting({ count }: { count: number }) {
  return (
    <>
      {count ? <Count>{count}</Count> : null}
      <Chevron />
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

/**
 * How far the members moved, summed over the chats with a count old enough
 * to compare: a person in two chats is in both. The line is the week of those
 * same chats.
 */
function MembersTile({ stats }: { stats: HomeStats }) {
  const { i18n } = useLingui();
  const { day, week } = memberChange(stats.members_delta);
  const counted = stats.members_delta.filter((entry) => entry.delta_7d !== null).length;
  const line = memberTrend(stats.members_week);
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
      {week === null ? null : (
        <small>
          <Plural
            value={counted}
            one="по # чату с замером"
            few="по # чатам с замером"
            many="по # чатам с замером"
            other="по # чатам с замером"
          />
        </small>
      )}
      {line ? (
        <svg
          aria-hidden="true"
          viewBox="-1 -2 102 36"
          preserveAspectRatio="none"
          className={css.tileLine}
        >
          <polyline points={line.points} vectorEffect="non-scaling-stroke" />
        </svg>
      ) : null}
    </div>
  );
}

/**
 * Who came to us in the last seven whole days, and in the seven before: the
 * Audience page's «пришли к нам», so the backfill's guesses are not in it.
 */
function CameTile({ came }: { came: AudienceOverview['came'] }) {
  const { i18n } = useLingui();
  const day = useDay();
  const from = day(came.compare_from);
  const total = i18n.number(came.total);
  const before = came.before === null ? '' : i18n.number(came.before);
  return (
    <div className={ui.summaryTile} data-tone="0">
      <span>
        <Trans>Пришли к нам за 7 дней</Trans>
      </span>
      <b>{came.now === null ? '—' : `+${i18n.number(came.now)}`}</b>
      <small>
        {came.before === null ? (
          <Trans>сравнение будет с {from}</Trans>
        ) : (
          <Trans>неделей раньше {before}</Trans>
        )}
      </small>
      <small>
        <Trans>за всё время {total}</Trans>
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
      wrap
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

/**
 * Who each bot can reach, each number with who it counts: the main bot by
 * whether it may write now, as the Audience page says it; the contact bot by
 * everyone who wrote to it; the old bots by who came through them.
 */
function Bots({
  audience,
  error,
  retry,
  ready,
  table: asTable,
  more,
}: {
  audience: AudienceOverview | undefined;
  error: Error | null;
  retry: () => void;
  ready: boolean | undefined;
  /** A table beside the queues in a browser; rows on a phone's width. */
  table: boolean;
  /** Opens the Audience page, which the browser's table links to. */
  more: () => void;
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
      {audience && !asTable ? (
        <BotRows audience={audience} />
      ) : audience ? (
        <>
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
                    <Trans>Кого считаем</Trans>
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
                  <td className={css.num}>{n(audience.main_bot.reachable)}</td>
                  <td>
                    <MainBotWho audience={audience} />
                  </td>
                  <td>{n(audience.main_bot.blocked)}</td>
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
                  <td className={css.num}>{n(audience.contact_bot.wrote)}</td>
                  <td>
                    <ContactBotWho audience={audience} />
                  </td>
                  <td>{n(audience.contact_bot.blocked)}</td>
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
                  <td className={css.num}>{n(audience.moved_bot)}</td>
                  <td>
                    <Trans>пришли к нам через старых ботов</Trans>
                  </td>
                  <td>—</td>
                </tr>
              </tbody>
            </table>
          </div>
          <button type="button" className={css.more} onClick={more}>
            <Trans>Аудитория подробно</Trans> <Chevron />
          </button>
        </>
      ) : error ? (
        <ConsoleFailure error={error} retry={retry} />
      ) : (
        <SkeletonRows count={2} />
      )}
    </>
  );
}

/** Who the main bot's number counts, as the Audience page words it. */
function MainBotWho({ audience }: { audience: AudienceOverview }) {
  const { i18n } = useLingui();
  const opted = i18n.number(audience.main_bot.opted_out);
  return audience.main_bot.opted_out ? (
    <Trans>дали писать и не заблокировали; ещё {opted} отписались от новостей</Trans>
  ) : (
    <Trans>дали писать и не заблокировали</Trans>
  );
}

/** Who the contact bot's number counts: everyone who wrote, whatever they used first. */
function ContactBotWho({ audience }: { audience: AudienceOverview }) {
  const { i18n } = useLingui();
  const ads = i18n.number(audience.contact_bot.ads_conversations);
  return <Trans>писали боту; из них о рекламе: {ads}</Trans>;
}

/** The bots table as rows: who each bot is, the number, and who it counts. */
function BotRows({ audience }: { audience: AudienceOverview }) {
  const { i18n } = useLingui();
  const n = (value: number) => i18n.number(value);
  // Kept whole on its line: «заблокировали» alone above «1» reads as nothing.
  const blocked = (count: number) => (
    <span style={{ whiteSpace: 'nowrap' }}>
      <Trans>заблокировали {n(count)}</Trans>
    </span>
  );
  return (
    <Rows>
      <Row
        wrap
        title={<Trans>Основной бот</Trans>}
        hint={
          <>
            <MainBotWho audience={audience} /> · {blocked(audience.main_bot.blocked)}
          </>
        }
        trailing={<Count>{n(audience.main_bot.reachable)}</Count>}
      />
      <Row
        wrap
        title={<Trans>Бот связи</Trans>}
        hint={
          <>
            <ContactBotWho audience={audience} /> ·{' '}
            {blocked(audience.contact_bot.blocked)}
          </>
        }
        trailing={<Count>{n(audience.contact_bot.wrote)}</Count>}
      />
      <Row
        wrap
        title={<Trans>Старые боты</Trans>}
        hint={<Trans>пришли к нам через старых ботов</Trans>}
        trailing={<Count>{n(audience.moved_bot)}</Count>}
      />
    </Rows>
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
