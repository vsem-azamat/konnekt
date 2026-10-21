import { Plural, Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { SearchIcon, TargetIcon } from '@/components/icons';
import {
  Chevron,
  Count,
  Hint,
  Label,
  Letters,
  Row,
  Rows,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { ProfileSheet } from '@/console/ProfileSheet';
import { adminCatalogQuery } from '@/console/queries';
import { daysSince } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * The catalog as the operator reads it: new profiles to look at, requests
 * nobody answered, and what people searched for and did not find. A profile
 * opens here, in a sheet, to be kept or hidden.
 * See catalog/docs/architecture.md, «The operator reads the catalog and runs the partner cards».
 */
export default function ConsoleCatalogPage() {
  return (
    <ConsoleGate>
      <Title>
        <Trans>Каталог</Trans>
      </Title>
      <Catalog />
    </ConsoleGate>
  );
}

function Days({ since }: { since: string }) {
  const days = daysSince(since);
  return days === 0 ? (
    <Trans>сегодня</Trans>
  ) : (
    <Plural value={days} one="# дн" few="# дн" many="# дн" other="# дн" />
  );
}

function Catalog() {
  const { data, isPending, error, refetch } = useQuery(adminCatalogQuery);
  const [opened, setOpened] = useState<number | null>(null);
  const open = (userId: number) => {
    hapticSelection();
    setOpened(userId);
  };

  if (isPending) {
    return (
      <div style={{ marginTop: 16 }}>
        <SkeletonRows count={4} />
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

  const { counts } = data;
  return (
    <>
      <div className={ui.stats}>
        <div className={ui.stat}>
          <b>{counts.profiles_week}</b>
          <span>
            <Trans>анкет за 7 дней</Trans>
          </span>
        </div>
        <div className={ui.stat}>
          <b>{counts.requests_week}</b>
          <span>
            <Trans>заявок за 7 дней</Trans>
          </span>
        </div>
        <div className={ui.stat}>
          <b>{counts.unanswered}</b>
          <span>
            <Trans>без откликов</Trans>
          </span>
        </div>
      </div>

      <Label aside={counts.profiles_to_review || null}>
        <Trans>Новые анкеты</Trans>
      </Label>
      {data.profiles.length > 0 ? (
        <Rows>
          {data.profiles.map((profile) => (
            <Row
              key={profile.user_id}
              leading={
                <Tile tone={0}>
                  <Letters text={profile.name.slice(0, 1).toUpperCase()} />
                </Tile>
              }
              title={profile.name}
              hint={
                // Hidden, and changed by its owner since: back for a decision.
                profile.status === 'banned' ? (
                  <Trans>скрыта, автор изменил анкету</Trans>
                ) : (
                  profile.services.join(', ')
                )
              }
              trailing={
                <>
                  <Count>
                    <Days since={profile.published_at} />
                  </Count>
                  <Chevron />
                </>
              }
              onClick={() => open(profile.user_id)}
            />
          ))}
        </Rows>
      ) : (
        <Hint>
          {counts.profiles_week ? (
            <Trans>Все новые анкеты просмотрены.</Trans>
          ) : (
            <Trans>За неделю новых анкет не было.</Trans>
          )}
        </Hint>
      )}

      {data.hidden.length > 0 ? (
        <>
          <Label aside={counts.hidden}>
            <Trans>Скрытые</Trans>
          </Label>
          <Rows>
            {data.hidden.map((profile) => (
              <Row
                key={profile.user_id}
                leading={
                  <Tile tone={4}>
                    <Letters text={profile.name.slice(0, 1).toUpperCase()} />
                  </Tile>
                }
                title={profile.name}
                hint={profile.services.join(', ')}
                trailing={<Chevron />}
                onClick={() => open(profile.user_id)}
              />
            ))}
          </Rows>
        </>
      ) : null}

      <Label
        aside={counts.unanswered > data.unanswered.length ? counts.unanswered : null}
      >
        <Trans>Заявки без откликов</Trans>
      </Label>
      {data.unanswered.length > 0 ? (
        <Rows>
          {data.unanswered.map((request) => (
            <Row
              key={request.id}
              leading={
                <Tile tone={4}>
                  <TargetIcon size={19} />
                </Tile>
              }
              title={request.text}
              trailing={
                <Count>
                  <Days since={request.created_at} />
                </Count>
              }
            />
          ))}
        </Rows>
      ) : (
        <Hint>
          <Trans>На все открытые заявки кто-то откликнулся.</Trans>
        </Hint>
      )}

      <Label aside={<Trans>30 дней</Trans>}>
        <Trans>Искали и не нашли</Trans>
      </Label>
      {data.failed_searches.length > 0 ? (
        <Rows>
          {data.failed_searches.map((search) => (
            <Row
              key={search.text}
              leading={
                <Tile tone={5}>
                  <SearchIcon size={19} />
                </Tile>
              }
              title={search.text}
              trailing={
                <Count>
                  <Plural
                    value={search.times}
                    one="# раз"
                    few="# раза"
                    many="# раз"
                    other="# раза"
                  />
                </Count>
              }
            />
          ))}
        </Rows>
      ) : (
        <Hint>
          <Trans>Всё, что искали, нашлось.</Trans>
        </Hint>
      )}
      {opened !== null ? (
        <ProfileSheet key={opened} userId={opened} onClose={() => setOpened(null)} />
      ) : null}
    </>
  );
}
