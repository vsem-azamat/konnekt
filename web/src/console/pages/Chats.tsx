import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';

import { SearchIcon } from '@/components/icons';
import { Sheet } from '@/components/Sheet';
import {
  Action,
  Actions,
  Chevron,
  Chips,
  ChipView,
  Hint,
  Label,
  Row,
  Rows,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { signed } from '@/console/activity';
import { useBrowserConsole } from '@/console/browserContext';
import table from '@/console/ChatTable.module.css';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import {
  type ChatTab,
  type ConsoleSection,
  catalogPlace,
  chatGuards,
  consoleSections,
  listedCount,
  tabCounts,
  tabOf,
} from '@/console/chats';
import { ChatFace } from '@/console/Faces';
import { FailureText } from '@/console/FailureText';
import { consoleChanges, consoleChatsQuery, consoleStatsQuery } from '@/console/queries';
import { type ConsoleChat, ConsoleError, type MemberDelta } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';

// The question first that asks something of the admin, «all» last.
const TABS: ChatTab[] = ['decide', 'listed', 'hidden', 'off', 'all'];

function isTab(value: string | null): value is ChatTab {
  return TABS.includes(value as ChatTab);
}

/** How a listed chat is there: the bot moderates it, watches it, or is not in it. */
const MODES = ['approved', 'observed', 'external'] as const;
type ListedMode = (typeof MODES)[number];

function isMode(value: string | null): value is ListedMode {
  return MODES.includes(value as ListedMode);
}

/**
 * Every chat the bot is in, for the people who run them. Unlike the public
 * directory this names member counts and the chats nobody approved yet.
 */
export default function ConsoleChatsPage() {
  return (
    <ConsoleGate wide>
      <Title>
        <Trans>Чаты</Trans>
      </Title>
      <ChatList />
    </ConsoleGate>
  );
}

function ChatList() {
  const { t } = useLingui();
  const navigate = useNavigate();
  const inBrowser = useBrowserConsole();
  const [params, setParams] = useSearchParams();
  const tabParam = params.get('tab');
  const tab: ChatTab = isTab(tabParam) ? tabParam : 'all';
  const modeParam = params.get('mode');
  const mode: ListedMode | null =
    tab === 'listed' && isMode(modeParam) ? modeParam : null;
  const [query, setQuery] = useState('');
  const [adding, setAdding] = useState(false);
  const { data, isPending, error, refetch } = useQuery(consoleChatsQuery);

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

  const counts = tabCounts(data);
  const modeCount = (key: ListedMode) =>
    data.filter((chat) => tabOf(chat) === 'listed' && chat.resource_status === key)
      .length;
  const listed = listedCount(data);
  const total = data.length;
  const sections = consoleSections(
    data,
    query,
    (chat) =>
      (tab === 'all' || tabOf(chat) === tab) &&
      (mode === null || chat.resource_status === mode),
  );
  const label: Record<ChatTab, string> = {
    decide: t`Нужно решение`,
    listed: t`В каталоге`,
    hidden: t`Скрыты`,
    off: t`Отключены`,
    all: t`Все`,
  };
  const modeLabel: Record<ListedMode, string> = {
    approved: t`Модерирует`,
    observed: t`Наблюдает`,
    external: t`Только ссылка`,
  };
  // Replaced, not pushed: a tab is a view of this screen, and back should
  // leave the screen rather than step through tabs.
  const show = (next: ChatTab, nextMode: ListedMode | null = null) => {
    hapticSelection();
    const search: Record<string, string> = {};
    if (next !== 'all') search.tab = next;
    if (nextMode) search.mode = nextMode;
    setParams(search, { replace: true });
  };

  return (
    <>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>
            В каталоге {listed} из {total}
          </Trans>
        </Sub>
      </div>
      {/* Chips, not a segmented control: five labels with counts do not fit
          one row of equal segments on a phone. */}
      <div style={{ marginTop: 14 }}>
        <Chips>
          {/* The chosen one stays, even at zero, so the page says what it shows. */}
          {TABS.filter((key) => key === 'all' || key === tab || counts[key] > 0).map(
            (key) => (
              <ChipView key={key} active={key === tab} onClick={() => show(key)}>
                {label[key]} {/* What waits for the admin is the one count in colour. */}
                <span className={key === 'decide' ? table.due : undefined}>
                  {counts[key]}
                </span>
              </ChipView>
            ),
          )}
        </Chips>
      </div>
      {tab === 'listed' ? (
        <div style={{ marginTop: 8 }}>
          <Chips>
            {/* The chosen one stays at zero, so the page says what it filters by. */}
            {MODES.filter((key) => modeCount(key) > 0 || key === mode).map((key) => (
              <ChipView
                key={key}
                active={key === mode}
                onClick={() => show('listed', key === mode ? null : key)}
              >
                {modeLabel[key]} {modeCount(key)}
              </ChipView>
            ))}
          </Chips>
        </div>
      ) : null}
      {/* In a browser the search and the button share a row; stretched to
          the table's width they were a phone's controls. */}
      <div className={inBrowser ? table.toolbar : undefined}>
        <div className={ui.field} style={{ marginTop: 12 }}>
          <SearchIcon size={18} className={ui.fieldIcon} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t`Название или id`}
            maxLength={80}
            style={{ all: 'unset', flex: 1, minWidth: 0 }}
          />
        </div>

        <div style={{ marginTop: 12 }}>
          <Actions>
            <Action quiet onClick={() => setAdding(true)}>
              <Trans>+ Внешний чат</Trans>
            </Action>
          </Actions>
        </div>
      </div>
      {adding ? (
        <AddExternalSheet
          onClose={() => setAdding(false)}
          onAdded={(chat) => navigate(`/console/chats/${chat.id}`)}
        />
      ) : null}

      {sections.length === 0 ? (
        <div style={{ marginTop: 16 }}>
          <Hint>
            <Trans>Таких чатов нет.</Trans>
          </Hint>
        </div>
      ) : inBrowser ? (
        <>
          <ChatTable sections={sections} />
          <div className={table.narrow}>
            <ChatRows sections={sections} />
          </div>
        </>
      ) : (
        <ChatRows sections={sections} />
      )}
    </>
  );
}

function ChatRows({ sections }: { sections: ConsoleSection[] }) {
  const navigate = useNavigate();
  return sections.map((section) => (
    <div key={sectionKey(section)}>
      <Label aside={section.chats.length}>
        <SectionName section={section} />
      </Label>
      <Rows>
        {section.chats.map((chat) => (
          <ChatLine
            key={chat.id}
            chat={chat}
            onOpen={() => {
              hapticSelection();
              navigate(`/console/chats/${chat.id}`);
            }}
          />
        ))}
      </Rows>
    </div>
  ));
}

function sectionKey(section: ConsoleSection): string {
  return section.key === 'group' ? `group-${section.root}` : section.key;
}

function SectionName({ section }: { section: ConsoleSection }) {
  return section.key === 'review' ? (
    <Trans>Нужно решение</Trans>
  ) : section.key === 'rest' ? (
    <Trans>Остальные</Trans>
  ) : (
    section.title
  );
}

/** What the bot does for newcomers, in words; null where the chat is not approved. */
function useGuardText(): (chat: ConsoleChat) => string | null {
  const { t } = useLingui();
  return (chat) => {
    const guards = chatGuards(chat);
    if (guards === null) return null;
    return guards.length
      ? guards
          .map((guard) => (guard === 'captcha' ? t`капча` : t`приветствие`))
          .join(', ')
      : t`без защиты`;
  };
}

/**
 * What the bot does in a chat, and whether students see it, in words: the two
 * things the console is asked about a chat, where the status names neither.
 */
function useChatWords() {
  const { t } = useLingui();
  const mode = (chat: ConsoleChat): string => {
    const word = {
      approved: t`модерирует`,
      observed: t`наблюдает`,
      external: t`только ссылка`,
      discovered: t`ждёт решения`,
      disabled: t`отключён`,
    }[chat.resource_status];
    // A chat without the bot has nothing to moderate or watch any more.
    return chat.bot_absent_at && chat.resource_status !== 'external'
      ? `${word} · ${t`бот вышел`}`
      : word;
  };
  const place = (chat: ConsoleChat): string => {
    switch (catalogPlace(chat)) {
      case 'listed':
        return t`в каталоге`;
      case 'no_link':
        return t`не в каталоге · нет ссылки`;
      case 'no_title':
        return t`не в каталоге · нет названия`;
      default:
        return t`не в каталоге`;
    }
  };
  return { mode, place };
}

/**
 * Every chat in one table, its sections as rows between them. The member
 * moves come from the summary's numbers, which count approved chats only;
 * a chat they miss, or a failed fetch, shows a dash.
 */
/** The table's columns, for the section rows that span them all. */
const COLUMNS = 6;

function ChatTable({ sections }: { sections: ConsoleSection[] }) {
  const { i18n } = useLingui();
  const guardText = useGuardText();
  const navigate = useNavigate();
  const stats = useQuery(consoleStatsQuery);
  const moves = new Map<number, MemberDelta>(
    (stats.data?.members_delta ?? []).map((entry) => [entry.chat_id, entry]),
  );
  const count = (n: number | null | undefined) => (n == null ? '—' : i18n.number(n));
  const move = (n: number | null | undefined) =>
    n == null ? '—' : signed(n, (abs) => i18n.number(abs));
  const words = useChatWords();
  const tone: Record<ConsoleChat['resource_status'], string | undefined> = {
    approved: table.good,
    discovered: table.warn,
    observed: undefined,
    external: undefined,
    disabled: undefined,
  };

  return (
    <div className={table.wrap}>
      <table className={table.table}>
        <thead>
          <tr>
            <th>
              <Trans>Чат</Trans>
            </th>
            <th>
              <Trans>Бот</Trans>
            </th>
            <th className={table.num}>
              <Trans>Участники</Trans>
            </th>
            <th className={table.num}>
              <Trans>Сутки</Trans>
            </th>
            <th className={table.num}>
              <Trans>7 дней</Trans>
            </th>
            <th>
              <Trans>Защита</Trans>
            </th>
          </tr>
        </thead>
        {sections.map((section) => (
          <tbody key={sectionKey(section)}>
            <tr className={table.section}>
              <th colSpan={COLUMNS} scope="rowgroup">
                <SectionName section={section} /> · {section.chats.length}
              </th>
            </tr>
            {section.chats.map((chat) => {
              const title = chat.title ?? String(chat.id);
              const moved = moves.get(chat.id);
              const to = `/console/chats/${chat.id}`;
              return (
                // The whole row opens the chat; the link in it is the way for
                // the keys and for readers.
                <tr
                  key={chat.id}
                  onClick={(event) => {
                    // A modified click is the link's to make, and a click
                    // that ends a selection is copying, not opening.
                    if (
                      event.button !== 0 ||
                      event.metaKey ||
                      event.ctrlKey ||
                      event.shiftKey
                    )
                      return;
                    if (window.getSelection()?.toString()) return;
                    navigate(to);
                  }}
                >
                  <td>
                    <span className={table.chat}>
                      <ChatFace chat={chat} size={34} tone={tileTone(chat)} />
                      <span>
                        <Link to={to} onClick={(event) => event.stopPropagation()}>
                          {title}
                        </Link>
                        <small className={placeClass(chat)}>{words.place(chat)}</small>
                      </span>
                    </span>
                  </td>
                  <td>
                    <span
                      className={[table.pill, tone[chat.resource_status]]
                        .filter(Boolean)
                        .join(' ')}
                    >
                      {words.mode(chat)}
                    </span>
                  </td>
                  <td className={table.num}>{count(chat.member_count)}</td>
                  <td className={table.num}>{move(moved?.delta_24h)}</td>
                  <td className={table.num}>{move(moved?.delta_7d)}</td>
                  <td>{guardText(chat) ?? '—'}</td>
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>
    </div>
  );
}

/**
 * How loud the catalogue label is: a chat decided on that students still do
 * not see is the surprise worth noticing, in the warm colour of a decision due.
 */
function placeClass(chat: ConsoleChat): string | undefined {
  const place = catalogPlace(chat);
  if (place === 'listed') return undefined;
  return place === 'no_link' || place === 'no_title' ? table.hidden : table.off;
}

function tileTone(chat: ConsoleChat): number {
  return chat.resource_status === 'discovered'
    ? 1
    : chat.resource_status === 'disabled'
      ? 5
      : 3;
}

function ChatLine({ chat, onOpen }: { chat: ConsoleChat; onOpen: () => void }) {
  const { i18n } = useLingui();
  const guardText = useGuardText();
  const words = useChatWords();
  const title = chat.title ?? String(chat.id);
  return (
    <Row
      leading={<ChatFace chat={chat} size={34} tone={tileTone(chat)} />}
      title={title}
      // Whether students see it first: on a phone the end of the line is cut.
      hint={
        <>
          <span className={placeClass(chat)}>{words.place(chat)}</span>
          {[
            words.mode(chat),
            chat.member_count !== null ? i18n.number(chat.member_count) : null,
            // Protection runs only where the bot moderates.
            guardText(chat),
          ]
            .filter(Boolean)
            .map((fact) => ` · ${fact}`)
            .join('')}
        </>
      }
      trailing={<Chevron />}
      onClick={onOpen}
    />
  );
}

/**
 * A chat the bot is not in, named by its public link. The server asks
 * Telegram for the rest, so a Telegram id is never typed here.
 */
function AddExternalSheet({
  onClose,
  onAdded,
}: {
  onClose: () => void;
  onAdded: (chat: ConsoleChat) => void;
}) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const [link, setLink] = useState('');
  const add = useMutation({
    mutationFn: (value: string) => consoleChanges.addExternalChat(value),
    onSuccess: (chat) => {
      void queryClient.invalidateQueries({ queryKey: consoleChatsQuery.queryKey });
      onAdded(chat);
    },
  });
  const value = link.trim();
  return (
    <Sheet title={t`Внешний чат`} closeLabel={t`Отмена`} onClose={onClose}>
      <Sub>
        <Trans>
          Публичная ссылка вида https://t.me/имя или @имя, или ссылка-приглашение
          https://t.me/+…. Бота туда не добавляем: чат попадёт в каталог с пометкой «не
          наш».
        </Trans>
      </Sub>
      <div className={ui.field}>
        <input
          value={link}
          onChange={(event) => setLink(event.target.value)}
          placeholder="https://t.me/cvut_fjfi"
          aria-label={t`Публичная ссылка`}
          maxLength={200}
          inputMode="url"
          style={{ all: 'unset', flex: 1, minWidth: 0 }}
        />
      </div>
      {add.error ? (
        <Hint>
          <AddFailure error={add.error} />
        </Hint>
      ) : null}
      <Actions>
        <Action
          disabled={add.isPending || value.length === 0}
          onClick={() => add.mutate(value)}
        >
          <Trans>Добавить в каталог</Trans>
        </Action>
      </Actions>
    </Sheet>
  );
}

/** Each refusal of `POST /api/chats/external` in words, by webapi's code for it. */
function AddFailure({ error }: { error: unknown }) {
  const detail = error instanceof ConsoleError ? error.detail : null;
  switch (detail) {
    case 'not_public':
      return (
        <Trans>
          Нужна ссылка вида https://t.me/имя, @имя или ссылка-приглашение https://t.me/+….
        </Trans>
      );
    case 'not_found':
      return <Trans>Telegram не знает чата по этой ссылке.</Trans>;
    case 'not_a_group':
      return <Trans>Это аккаунт человека, а не чат или канал.</Trans>;
    case 'already_known':
      return <Trans>Этот чат уже есть в списке: режим меняется на его странице.</Trans>;
    case 'telegram_unavailable':
      return <Trans>Telegram сейчас не ответил. Попробуйте через минуту.</Trans>;
    default:
      return <FailureText error={error} />;
  }
}
