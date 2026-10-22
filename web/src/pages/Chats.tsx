import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { type ReactNode, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { ChatRow, ChatTitle, Members } from '@/components/ChatRow';
import { CloseIcon, SearchIcon } from '@/components/icons';
import { CityName, TopicHeading } from '@/components/Place';
import { TabBar } from '@/components/TabBar';
import {
  Action,
  Chevron,
  Chips,
  ChipView,
  Empty,
  Label,
  Letters,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { useReportEmpty } from '@/hooks/useReportEmpty';
import { chatsQuery, institutionsQuery, meQuery } from '@/lib/api';
import {
  blocks,
  cities,
  cityChoices,
  defaultCity,
  type Entry,
  initials,
  ownUniversity,
  type PublicChat,
  search,
  sectionAvatar,
  sectionHint,
  sectionLead,
  sectionMembers,
} from '@/lib/chats';

/** The address's word for «Все»: no city at all, chosen rather than defaulted to. */
const ALL = 'all';

/** What people search by, said in the field and again when nothing matched. */
const EXAMPLES = 'ČVUT, FIT, Strahov';

/**
 * The chat directory: supervisor-telegram's chats, read as places to go.
 *
 * How entries are built is in catalog/docs/architecture.md, «The chat directory
 * reads the order it is given», and in `lib/chats.ts`.
 */
export default function ChatsPage() {
  const { t } = useLingui();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const field = useRef<HTMLInputElement>(null);
  // Back in the field either way: the empty block holding one of the two
  // buttons disappears with the query, and focus would fall to the page.
  const clear = () => {
    setQuery('');
    field.current?.focus();
  };

  // The error as soon as it happens, with its own button to ask again. The
  // default two silent retries kept the skeleton up for seconds, and a person
  // who sees the error can retry when they like.
  const { data, isPending, isError, refetch } = useQuery({ ...chatsQuery, retry: false });

  // A student's own university first. Outside Telegram there is no one to
  // ask, and the directory keeps supervisor's order.
  const me = useQuery(meQuery);
  // Loaded with the screen, not on the first keystroke: it holds the
  // universities' cities, and a search typed before it arrived would say
  // «Такого чата нет» for a city it simply had not heard of yet. A faculty
  // needs it too, since the taxonomy names the university above it.
  const institutions = useQuery(institutionsQuery);
  const cityOf = useMemo(() => cities(institutions.data ?? []), [institutions.data]);
  const found = useMemo(
    () => (data ? search(data, query, cityOf) : []),
    [data, query, cityOf],
  );
  const mine = ownUniversity(me.data?.institution, institutions.data ?? []);
  // The city lives in the address, so Back from a section returns to the one
  // the reader picked rather than to the default.
  const [params, setParams] = useSearchParams();
  const choices = useMemo(() => cityChoices(data ?? []), [data]);
  const picked = params.get('city');
  const city =
    picked === ALL
      ? null
      : picked !== null && choices.includes(picked)
        ? picked
        : defaultCity(choices, mine === null ? null : cityOf.get(mine));
  const pick = (next: string | null) =>
    setParams(
      (now) => {
        now.set('city', next ?? ALL);
        return now;
      },
      { replace: true },
    );
  // The default is the reader's university's city, which needs the profile
  // and the taxonomy. Until both answered the list waits rather than show
  // «Все» and jump under a finger to another city. Their first answer, data or
  // error, not `isPending`: a query that failed goes back to pending when it
  // is asked again, and the list would turn into a skeleton under the reader.
  const waitingForHome = picked === null && !(me.isFetched && institutions.isFetched);
  const shown = useMemo(() => blocks(data ?? [], { mine, city }), [data, mine, city]);
  const searching = query.trim() !== '';
  // Where a loose chat is, under its name: «вся Чехия» always, its city only
  // when the list is not already one city's.
  const where = (chat: PublicChat): ReactNode =>
    chat.city === null || city === null ? <CityName city={chat.city} /> : undefined;
  let tone = 0;
  useReportEmpty(data !== undefined && data.length === 0, 'chat directory');

  return (
    <>
      <Screen withTabs>
        <AppHeader />
        <Title>
          <Trans>Найди свой чат</Trans>
        </Title>
        <div style={{ marginTop: 6 }}>
          <Sub>
            <Trans>
              Факультеты, общежития, общие. В наших чатах вычищаем спам, скам и фишинг.
            </Trans>
          </Sub>
        </div>

        <div className={ui.field} style={{ marginTop: 16 }}>
          <SearchIcon size={18} className={ui.fieldIcon} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            ref={field}
            placeholder={`${EXAMPLES}…`}
            aria-label={t`Поиск чата`}
            maxLength={100}
            style={{ all: 'unset', flex: 1, minWidth: 0 }}
          />
          {query !== '' ? (
            <button
              type="button"
              className={ui.fieldClear}
              aria-label={t`Очистить поиск`}
              // Keeps the field focused, so the keyboard does not drop and
              // come back, moving Telegram's viewport with it.
              onPointerDown={(event) => event.preventDefault()}
              onClick={clear}
            >
              <CloseIcon size={14} />
            </button>
          ) : null}
        </div>

        {/* Not while searching: a search looks through every city. */}
        {choices.length > 1 && !searching ? (
          <fieldset className={ui.cities} aria-label={t`Город`}>
            <Chips>
              <ChipView
                active={city === null}
                pressed={city === null}
                onClick={() => pick(null)}
              >
                <Trans>Все</Trans>
              </ChipView>
              {choices.map((choice) => (
                <ChipView
                  key={choice}
                  active={city === choice}
                  pressed={city === choice}
                  onClick={() => pick(choice)}
                >
                  <CityName city={choice} />
                </ChipView>
              ))}
            </Chips>
          </fieldset>
        ) : null}

        {isPending || waitingForHome ? (
          <>
            <Label>
              <Trans>Загружаем</Trans>
            </Label>
            <SkeletonRows count={6} />
          </>
        ) : isError ? (
          // Not the cause: the screen cannot tell the network from the server.
          <div className={ui.stateBlock}>
            <Empty
              title={<Trans>Не удалось загрузить чаты</Trans>}
              body={<Trans>Список не пришёл. Попробуй ещё раз через минуту.</Trans>}
              action={
                <Action onClick={() => void refetch()}>
                  <Trans>Попробовать ещё раз</Trans>
                </Action>
              }
            />
          </div>
        ) : searching ? (
          found.length === 0 ? (
            <div className={ui.stateBlock}>
              <Empty
                title={<Trans>Такого чата нет</Trans>}
                body={<Trans>Ищи по вузу, факультету или общежитию: {EXAMPLES}.</Trans>}
                action={
                  <Action quiet onClick={clear}>
                    <Trans>Очистить поиск</Trans>
                  </Action>
                }
              />
            </div>
          ) : (
            <>
              <Label>
                <Trans>Нашлось</Trans>
              </Label>
              <Rows>
                {found.map((chat, index) => (
                  <ChatRow key={chat.link} chat={chat} tone={index} />
                ))}
              </Rows>
            </>
          )
        ) : shown.length === 0 ? (
          <Empty title={<Trans>Чатов пока нет</Trans>} />
        ) : (
          shown.map((block) => (
            <div key={block.heading}>
              <Label aside={block.entries.length}>
                <TopicHeading topic={block.heading} />
                {block.heading === 'university' && city !== null ? (
                  <>
                    {' · '}
                    <CityName city={city} />
                  </>
                ) : null}
              </Label>
              <Rows>
                {block.entries.map((entry) =>
                  entry.kind === 'section' ? (
                    <SectionRow
                      key={`section:${entry.name}`}
                      section={entry}
                      tone={tone++}
                      onOpen={() => navigate(`/chats/${encodeURIComponent(entry.name)}`)}
                    />
                  ) : (
                    <ChatRow
                      key={entry.chat.link}
                      chat={entry.chat}
                      tone={tone++}
                      hint={where(entry.chat)}
                    />
                  ),
                )}
              </Rows>
            </div>
          ))
        )}
      </Screen>
      <TabBar />
    </>
  );
}

/** A university with its own screen: its chat's photo, people and activity, and what else is in it. */
function SectionRow({
  section,
  tone,
  onOpen,
}: {
  section: Extract<Entry, { kind: 'section' }>;
  tone: number;
  onOpen: () => void;
}) {
  const lead = sectionLead(section);
  const external = lead?.external ?? false;
  return (
    <Row
      leading={
        <Tile tone={tone} round photo={sectionAvatar(section)}>
          <Letters text={initials(section.name)} />
        </Tile>
      }
      title={<ChatTitle title={section.name} external={external} />}
      hint={<SectionHint section={section} />}
      trailing={
        <>
          <Members
            count={sectionMembers(section)}
            activity={lead?.activity ?? 'unknown'}
          />
          <Chevron />
        </>
      }
      outline={external}
      onClick={onOpen}
    />
  );
}

/** «ещё 6 чатов: Kajetánka, …»: «ещё» because the row's title is one of them. */
function SectionHint({ section }: { section: Extract<Entry, { kind: 'section' }> }) {
  const { count, names, more } = sectionHint(section);
  return more ? (
    <Plural
      value={count}
      one={`ещё # чат: ${names}`}
      few={`ещё # чата: ${names}`}
      many={`ещё # чатов: ${names}`}
      other={`ещё # чата: ${names}`}
    />
  ) : (
    <Plural
      value={count}
      one={`# чат: ${names}`}
      few={`# чата: ${names}`}
      many={`# чатов: ${names}`}
      other={`# чата: ${names}`}
    />
  );
}
