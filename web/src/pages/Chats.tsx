import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { ChatRow } from '@/components/ChatRow';
import { SearchIcon } from '@/components/icons';
import { TabBar } from '@/components/TabBar';
import {
  Chevron,
  Count,
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
  cities,
  directory,
  initials,
  ownUniversity,
  search,
  sectionAvatar,
  sectionHint,
} from '@/lib/chats';

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

  const { data, isPending, isError, refetch } = useQuery(chatsQuery);

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
  const { entries, rest } = useMemo(() => directory(data ?? [], mine), [data, mine]);
  const searching = query.trim() !== '';
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
            <Trans>Факультеты, общежития, общие. Спам, скам и фишинг мы вычищаем.</Trans>
          </Sub>
        </div>

        <div className={ui.field} style={{ marginTop: 16 }}>
          <SearchIcon size={18} className={ui.fieldIcon} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t`ČVUT, FIT, Strahov…`}
            aria-label={t`Поиск чата`}
            maxLength={100}
            style={{ all: 'unset', flex: 1, minWidth: 0 }}
          />
        </div>

        {isPending ? (
          <>
            <Label>
              <Trans>Загружаем</Trans>
            </Label>
            <SkeletonRows count={6} />
          </>
        ) : isError ? (
          <Rows>
            <Row
              title={<Trans>Не удалось загрузить чаты</Trans>}
              hint={<Trans>Нажми, чтобы попробовать ещё раз</Trans>}
              onClick={() => void refetch()}
            />
          </Rows>
        ) : searching ? (
          found.length === 0 ? (
            <Empty title={<Trans>Такого чата нет</Trans>} />
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
        ) : entries.length === 0 && rest.length === 0 ? (
          <Empty title={<Trans>Чатов пока нет</Trans>} />
        ) : (
          <>
            {entries.length > 0 ? (
              // No heading: supervisor's groups are parent chats, not a
              // category this screen could name. See catalog/docs/architecture.md.
              <div style={{ marginTop: 18 }}>
                <Rows>
                  {entries.map((entry, index) =>
                    entry.kind === 'section' ? (
                      <Row
                        key={`section:${entry.name}`}
                        leading={
                          <Tile tone={index} round photo={sectionAvatar(entry)}>
                            <Letters text={initials(entry.name)} />
                          </Tile>
                        }
                        title={entry.name}
                        hint={sectionHint(entry)}
                        trailing={
                          <>
                            <Count>{entry.chats.length}</Count>
                            <Chevron />
                          </>
                        }
                        onClick={() =>
                          navigate(`/chats/${encodeURIComponent(entry.name)}`)
                        }
                      />
                    ) : (
                      <ChatRow key={entry.chat.link} chat={entry.chat} tone={index} />
                    ),
                  )}
                </Rows>
              </div>
            ) : null}
            {rest.length > 0 ? (
              <>
                <Label>
                  <Trans>Остальные</Trans>
                </Label>
                <Rows>
                  {rest.map((chat, index) => (
                    <ChatRow key={chat.link} chat={chat} tone={entries.length + index} />
                  ))}
                </Rows>
              </>
            ) : null}
          </>
        )}
      </Screen>
      <TabBar />
    </>
  );
}
