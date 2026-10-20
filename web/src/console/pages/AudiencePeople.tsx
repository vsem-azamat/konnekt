import { Trans, useLingui } from '@lingui/react/macro';
import { useInfiniteQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { SearchIcon } from '@/components/icons';
import {
  Action,
  Chips,
  ChipView,
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
import { useAudienceLabels } from '@/console/AudienceLabels';
import {
  type AudienceFilters,
  type AudienceStatus,
  STATUSES,
  TOUCHPOINTS,
  type Touchpoint,
} from '@/console/audience';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { audiencePeopleQuery } from '@/console/queries';
import { personName, utc } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';
import { initials } from '@/lib/chats';

/** Everybody in the audience, newest activity first, filtered by where they came and whether the bot may write. */
export default function ConsoleAudiencePeoplePage() {
  return (
    <ConsoleGate>
      <Title>
        <Trans>Люди</Trans>
      </Title>
      <People />
    </ConsoleGate>
  );
}

function People() {
  const { t, i18n } = useLingui();
  const navigate = useNavigate();
  const labels = useAudienceLabels();
  const [params, setParams] = useSearchParams();
  const [typed, setTyped] = useState(params.get('q') ?? '');

  const touchpoint = TOUCHPOINTS.find((key) => key === params.get('touchpoint'));
  const status = STATUSES.find((key) => key === params.get('status'));
  const newThisWeek = params.get('new') === 'week';
  const filters: AudienceFilters = {
    touchpoint,
    status,
    q: params.get('q') ?? undefined,
    new_days: newThisWeek ? 7 : undefined,
  };
  const {
    data,
    isPending,
    error,
    refetch,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  } = useInfiniteQuery(audiencePeopleQuery(filters));

  // Replaced, not pushed: a filter is a view of this screen, and back should leave it.
  const set = (key: string, value: string | undefined) => {
    hapticSelection();
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  const items = data?.pages.flatMap((page) => page.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;

  return (
    <>
      <form
        className={ui.field}
        style={{ marginTop: 12 }}
        onSubmit={(event) => {
          event.preventDefault();
          set('q', typed.trim() || undefined);
        }}
      >
        <SearchIcon size={18} className={ui.fieldIcon} />
        <input
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          onBlur={() => set('q', typed.trim() || undefined)}
          placeholder={t`@username, имя или id`}
          maxLength={64}
          enterKeyHint="search"
          style={{ all: 'unset', flex: 1, minWidth: 0 }}
        />
      </form>
      <div style={{ marginTop: 12 }}>
        <Chips>
          <ChipView active={!touchpoint} onClick={() => set('touchpoint', undefined)}>
            <Trans>Все</Trans>
          </ChipView>
          {TOUCHPOINTS.map((key: Touchpoint) => (
            <ChipView
              key={key}
              active={key === touchpoint}
              onClick={() => set('touchpoint', key)}
            >
              {labels.touchpoint[key]}
            </ChipView>
          ))}
        </Chips>
      </div>
      <div style={{ marginTop: 8 }}>
        <Chips>
          {STATUSES.map((key: AudienceStatus) => (
            <ChipView
              key={key}
              active={key === status}
              onClick={() => set('status', key === status ? undefined : key)}
            >
              {labels.status[key]}
            </ChipView>
          ))}
          <ChipView
            active={newThisWeek}
            onClick={() => set('new', newThisWeek ? undefined : 'week')}
          >
            <Trans>новые за неделю</Trans>
          </ChipView>
        </Chips>
      </div>

      {isPending ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={6} />
        </div>
      ) : error || !data ? (
        <div style={{ marginTop: 16 }}>
          <ConsoleFailure error={error} retry={() => void refetch()} />
        </div>
      ) : (
        <>
          <Label aside={total}>
            <Trans>Последняя активность</Trans>
          </Label>
          {items.length === 0 ? (
            <Hint>
              <Trans>Никого не нашлось.</Trans>
            </Hint>
          ) : (
            <Rows>
              {items.map((person) => {
                const name = personName(person);
                return (
                  <Row
                    key={person.user_id}
                    leading={
                      <Tile tone={3}>
                        <Letters text={initials(name.replace('@', ''))} />
                      </Tile>
                    }
                    title={name}
                    hint={
                      <span className={ui.touchpoints}>
                        {person.touchpoints.map((key) => (
                          <span key={key}>{labels.touchpoint[key] ?? key}</span>
                        ))}
                        {person.language_code ? (
                          <span>{person.language_code}</span>
                        ) : null}
                      </span>
                    }
                    trailing={
                      <span style={{ textAlign: 'right', fontSize: 12 }}>
                        {i18n.date(utc(person.last_seen_at), {
                          day: 'numeric',
                          month: 'short',
                        })}
                        <br />
                        <span className={ui.statusText} data-status={person.status}>
                          {labels.status[person.status]}
                        </span>
                      </span>
                    }
                    onClick={() => {
                      hapticSelection();
                      navigate(`/console/audience/${person.user_id}`);
                    }}
                  />
                );
              })}
            </Rows>
          )}
          {hasNextPage ? (
            <div className={ui.actionsStacked}>
              <Action
                quiet
                disabled={isFetchingNextPage}
                onClick={() => void fetchNextPage()}
              >
                <Trans>Показать ещё</Trans>
              </Action>
            </div>
          ) : null}
        </>
      )}
    </>
  );
}
