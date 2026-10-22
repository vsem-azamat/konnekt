import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

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
  Letters,
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
  consoleSections,
  isListed,
  joinsDirectly,
  type StatusFilter,
  statusCounts,
} from '@/console/chats';
import { FailureText } from '@/console/FailureText';
import { consoleChanges, consoleChatsQuery } from '@/console/queries';
import { type ConsoleChat, ConsoleError } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';
import { initials } from '@/lib/chats';

const FILTERS: StatusFilter[] = [
  'all',
  'discovered',
  'approved',
  'observed',
  'external',
  'disabled',
];

function isFilter(value: string | null): value is StatusFilter {
  return FILTERS.includes(value as StatusFilter);
}

/**
 * Every chat the bot is in, for the people who run them. Unlike the public
 * directory this names member counts and the chats nobody approved yet.
 */
export default function ConsoleChatsPage() {
  return (
    <ConsoleGate>
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
  const [params, setParams] = useSearchParams();
  const status = params.get('status');
  const filter: StatusFilter = isFilter(status) ? status : 'all';
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

  const counts = statusCounts(data);
  const sections = consoleSections(data, filter, query);
  const label: Record<StatusFilter, string> = {
    all: t`Все`,
    discovered: t`На проверке`,
    approved: t`Одобрены`,
    observed: t`Наблюдаем`,
    external: t`Внешние`,
    disabled: t`Откл.`,
  };

  return (
    <>
      {/* Chips, not a segmented control: four labels with counts do not fit
          one row of equal segments on a phone. */}
      <div style={{ marginTop: 14 }}>
        <Chips>
          {/* The chosen one stays, even at zero, so the page says what it shows. */}
          {FILTERS.filter(
            (key) => key === 'all' || key === filter || counts[key] > 0,
          ).map((key) => (
            <ChipView
              key={key}
              active={key === filter}
              onClick={() => {
                hapticSelection();
                // Replaced, not pushed: a filter is a view of this screen, and
                // back should leave the screen rather than step through filters.
                setParams(key === 'all' ? {} : { status: key }, { replace: true });
              }}
            >
              {label[key]} {counts[key]}
            </ChipView>
          ))}
        </Chips>
      </div>
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
      ) : (
        sections.map((section) => (
          <div key={section.key === 'group' ? `group-${section.root}` : section.key}>
            <Label aside={section.chats.length}>
              {section.key === 'review' ? (
                <Trans>На проверке</Trans>
              ) : section.key === 'rest' ? (
                <Trans>Остальные</Trans>
              ) : (
                section.title
              )}
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
        ))
      )}
    </>
  );
}

function ChatLine({ chat, onOpen }: { chat: ConsoleChat; onOpen: () => void }) {
  const { t, i18n } = useLingui();
  const title = chat.title ?? String(chat.id);
  const guards = [
    // Where people walk straight in, a stored captcha asks nobody.
    chat.join_mode === 'captcha' && !joinsDirectly(chat) ? t`капча` : null,
    chat.is_welcome_enabled ? t`приветствие` : null,
  ].filter(Boolean);
  // Protection runs only where the bot is approved; elsewhere the status is
  // the thing to know.
  const facts =
    chat.resource_status === 'approved'
      ? [
          chat.member_count !== null ? i18n.number(chat.member_count) : null,
          guards.length ? guards.join(', ') : t`без защиты`,
          isListed(chat) ? t`на сайте` : t`не на сайте`,
        ]
      : chat.resource_status === 'observed' || chat.resource_status === 'external'
        ? [
            chat.member_count !== null ? i18n.number(chat.member_count) : null,
            chat.resource_status === 'observed' ? t`наблюдаем` : t`внешний`,
            isListed(chat) ? t`на сайте` : t`не на сайте`,
          ]
        : [
            chat.member_count !== null ? i18n.number(chat.member_count) : null,
            chat.resource_status === 'discovered' ? t`на проверке` : t`отключён`,
          ];
  const tone =
    chat.resource_status === 'discovered'
      ? 1
      : chat.resource_status === 'disabled'
        ? 5
        : 3;

  return (
    <Row
      leading={
        <Tile tone={tone}>
          <Letters text={initials(title)} />
        </Tile>
      }
      title={title}
      hint={facts.filter(Boolean).join(' · ')}
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
          Публичная ссылка вида https://t.me/имя или @имя. Бота туда не добавляем: чат
          попадёт в каталог с пометкой «не наш».
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
          Нужна публичная ссылка вида https://t.me/имя или @имя. По ссылке-приглашению чат
          не найти.
        </Trans>
      );
    case 'not_found':
      return <Trans>Telegram не знает публичного чата с таким именем.</Trans>;
    case 'not_a_group':
      return <Trans>Это канал или человек, а не чат.</Trans>;
    case 'already_known':
      return <Trans>Этот чат уже есть в списке: режим меняется на его странице.</Trans>;
    case 'telegram_unavailable':
      return <Trans>Telegram сейчас не ответил. Попробуйте через минуту.</Trans>;
    default:
      return <FailureText error={error} />;
  }
}
