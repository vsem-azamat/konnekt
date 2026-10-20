import { Plural, Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useNavigate } from 'react-router';
import {
  BagIcon,
  ChatIcon,
  DocumentIcon,
  PersonIcon,
  ShieldIcon,
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
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import {
  adminCatalogQuery,
  adminPartnersQuery,
  blockedQuery,
  consoleChatsQuery,
  consoleStatsQuery,
} from '@/console/queries';
import { type AttentionKey, attention } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * The console's first screen: what needs a look, then its sections.
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
  const stats = useQuery(consoleStatsQuery);
  const chats = useQuery(consoleChatsQuery);
  const catalog = useQuery(adminCatalogQuery);
  const partners = useQuery(adminPartnersQuery);
  const blocked = useQuery(blockedQuery);

  const open = (path: string) => {
    hapticSelection();
    navigate(path);
  };

  // Each backend answers for itself: webapi refusing must not hide what the
  // catalog said, and the other way round.
  const webapiError = stats.error ?? chats.error;
  const loading =
    catalog.isPending || (!webapiError && (stats.isPending || chats.isPending));
  const items = attention({
    adsToday: stats.data?.spam_pings.count_24h ?? 0,
    chats: chats.data ?? [],
    profilesWeek: catalog.data?.counts.profiles_week ?? 0,
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
        title={<Trans>Реклама за сутки</Trans>}
        hint={
          <Trans>
            детектор, все чаты · {stats.data?.spam_pings.count_7d ?? 0} за неделю
          </Trans>
        }
        trailing={<Count>{count}</Count>}
        onClick={() => open('/console/spam')}
      />
    ),
    review: (count) => (
      <Row
        key="review"
        leading={
          <Tile tone={1}>
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
          <Tile tone={0}>
            <PersonIcon size={19} />
          </Tile>
        }
        title={<Trans>Новые анкеты за неделю</Trans>}
        trailing={<Count>{count}</Count>}
        onClick={() => open('/console/catalog')}
      />
    ),
  };

  return (
    <>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>Что происходит в чатах и в каталоге.</Trans>
        </Sub>
      </div>

      <Label>
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
