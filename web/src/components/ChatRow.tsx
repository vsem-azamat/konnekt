import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { hapticSelection } from '@/hooks/useTelegram';
import { api, institutionsQuery, rawInitData } from '@/lib/api';
import { joinFromCatalog } from '@/lib/catalogPass';
import { chatPreview } from '@/lib/chatPreview';
import {
  type Activity,
  chipFor,
  initials,
  type PublicChat,
  placeOf,
  rowDotFor,
} from '@/lib/chats';
import { MegaphoneIcon, PersonIcon } from './icons';
import { CityName, TopicWord } from './Place';
import { Sheet } from './Sheet';
import { Action, Chevron, Count, Hint, Letters, Row, Tile } from './Ui';
import css from './ui.module.css';

/** Supervisor's word for how much a chat talks, and nothing for `unknown`. */
export function ActivityChip({ activity }: { activity: Activity }) {
  const chip = chipFor(activity);
  if (chip === null) return null;
  return (
    <span
      className={chip === 'busy' ? `${css.activity} ${css.activityBusy}` : css.activity}
    >
      <ActivityWord activity={activity} />
    </span>
  );
}

function ActivityWord({ activity }: { activity: Activity }) {
  switch (chipFor(activity)) {
    case 'busy':
      return <Trans>оживлённый</Trans>;
    case 'active':
      return <Trans>активный</Trans>;
    case 'quiet':
      return <Trans>тихий</Trans>;
    default:
      return null;
  }
}

/**
 * How many people a row's chat has, beside its chevron, and a dot for how much
 * it talks: filled for «оживлённый», a ring for «активный». The words are for
 * a screen reader. Nothing when never measured and quiet.
 *
 * A channel's people are subscribers, and it has no talk to measure: the same
 * figure with no dot, and the reader hears «подписчиков».
 */
export function Members({
  count,
  activity,
  channel,
}: {
  count: number | null;
  activity: Activity;
  channel: boolean;
}) {
  const { i18n } = useLingui();
  const dot = channel ? null : rowDotFor(activity);
  if (count === null && dot === null) return null;
  return (
    <Count>
      <span className={css.people}>
        {dot ? (
          <span
            className={
              dot === 'busy' ? `${css.dot} ${css.dotBusy}` : `${css.dot} ${css.dotActive}`
            }
            aria-hidden="true"
          />
        ) : null}
        {count === null ? null : (
          <>
            <PersonIcon size={13} />
            {i18n.number(count)}
            <span className={css.srOnly}>
              {' '}
              {channel ? (
                <Plural
                  value={count}
                  one="подписчик"
                  few="подписчика"
                  many="подписчиков"
                  other="подписчика"
                />
              ) : (
                <Plural
                  value={count}
                  one="участник"
                  few="участника"
                  many="участников"
                  other="участника"
                />
              )}
            </span>
          </>
        )}
        {!channel && chipFor(activity) ? (
          <span className={css.srOnly}>
            {', '}
            <ActivityWord activity={activity} />
          </span>
        ) : null}
      </span>
    </Count>
  );
}

/** A chat's name, and «не наш» after it when somebody else runs the chat. */
export function ChatTitle({
  title,
  external,
  channel,
}: {
  title: string;
  external: boolean;
  channel: boolean;
}) {
  if (!external) return <>{title}</>;
  return (
    <span className={css.nameLine}>
      <span className={css.name}>{title}</span>
      <NotOurs />
      <NotOursSaid channel={channel} />
    </span>
  );
}

/** What a screen reader hears for the plaque. */
function NotOursSaid({ channel }: { channel: boolean }) {
  return (
    <span className={css.srOnly}>
      {', '}
      {channel ? <Trans>не наш канал</Trans> : <Trans>не наш чат</Trans>}
    </span>
  );
}

/**
 * A chat's photo or letters. A channel's has a megaphone at its lower right,
 * which says it is read rather than talked in; a screen reader is told by the
 * count's «подписчиков» instead.
 */
function Avatar({ chat, tone }: { chat: PublicChat; tone: number }) {
  const tile = (
    <Tile tone={tone} round photo={chat.avatar}>
      <Letters text={initials(chat.title)} />
    </Tile>
  );
  if (chat.kind !== 'channel') return tile;
  return (
    <span className={css.avatarWithBadge}>
      {tile}
      <span className={css.channelBadge} aria-hidden="true">
        <MegaphoneIcon size={10} strokeWidth={2.2} />
      </span>
    </span>
  );
}

/** The plaque on somebody else's chat. Read out by the words beside it instead. */
function NotOurs() {
  return (
    <span className={css.notOurs} aria-hidden="true">
      <Trans>не наш</Trans>
    </span>
  );
}

/**
 * One chat. A tap shows what it is; only «Открыть чат» leaves for Telegram.
 *
 * The app holds no conversations, only the way in, and the way in used to be
 * the tap itself: a reader who touched a row to see what it was found
 * themselves outside the app. The preview is a sheet rather than a screen so
 * the list, and where it was scrolled to, is still there when it closes. It
 * lives in the history, so Back closes it: see `lib/chatPreview.ts`.
 */
export function ChatRow({
  chat,
  tone,
  hint,
}: {
  chat: PublicChat;
  tone: number;
  /** The line under the name: where the chat is, when the list does not say it already. */
  hint?: ReactNode;
}) {
  const preview = chatPreview(chat.link, useLocation(), {
    navigate: useNavigate(),
    openLink: () =>
      joinFromCatalog(chat, {
        initData: rawInitData,
        claim: api.claimCatalogPass,
        openLink: openTelegramLink,
      }),
    // react-router keeps a location's state under `usr` in the history entry,
    // and writes it there synchronously on navigate.
    stateNow: () => (window.history.state as { usr?: unknown } | null)?.usr,
  });
  const channel = chat.kind === 'channel';
  return (
    <>
      <Row
        leading={<Avatar chat={chat} tone={tone} />}
        title={
          <ChatTitle title={chat.title} external={chat.external} channel={channel} />
        }
        hint={hint}
        trailing={
          <>
            <Members
              count={chat.member_count}
              activity={chat.activity}
              channel={channel}
            />
            <Chevron />
          </>
        }
        outline={chat.external}
        onClick={() => {
          hapticSelection();
          preview.show();
        }}
      />
      {preview.open ? (
        <ChatPreview
          chat={chat}
          tone={tone}
          onClose={preview.close}
          onJoin={preview.join}
        />
      ) : null}
    </>
  );
}

function ChatPreview({
  chat,
  tone,
  onClose,
  onJoin,
}: {
  chat: PublicChat;
  tone: number;
  onClose: () => void;
  onJoin: () => void;
}) {
  const { t } = useLingui();
  // Already loaded by the Chats tab for its search; a section's screen asks for
  // it here, and until it comes the line has the chat's own city only.
  const institutions = useQuery(institutionsQuery);
  const place = placeOf(chat, institutions.data ?? []);
  const channel = chat.kind === 'channel';
  const hasFacts =
    chat.member_count !== null ||
    (!channel && chipFor(chat.activity) !== null) ||
    chat.is_forum;

  return (
    <Sheet
      title={
        <span className={css.chatHead}>
          <Tile tone={tone} large round photo={chat.avatar}>
            <Letters text={initials(chat.title)} />
          </Tile>
          <span className={css.chatHeadBody}>
            <span>{chat.title}</span>
            <span className={`${css.chatPlace} ${css.nameLine}`}>
              {chat.external ? <NotOurs /> : null}
              <span className={css.name}>
                {place.university ??
                  (chat.topic ? <TopicWord topic={chat.topic} /> : null)}
                {place.university || chat.topic ? ' · ' : null}
                <CityName city={place.city} />
              </span>
              {chat.external ? <NotOursSaid channel={channel} /> : null}
            </span>
          </span>
        </span>
      }
      onClose={onClose}
      closeLabel={t`Закрыть`}
    >
      {hasFacts ? (
        <div className={css.facts}>
          {chat.member_count !== null ? (
            <span className={css.fact}>
              {channel ? (
                <Plural
                  value={chat.member_count}
                  one="# подписчик"
                  few="# подписчика"
                  many="# подписчиков"
                  other="# подписчика"
                />
              ) : (
                <Plural
                  value={chat.member_count}
                  one="# участник"
                  few="# участника"
                  many="# участников"
                  other="# участника"
                />
              )}
            </span>
          ) : null}
          {channel ? null : <ActivityChip activity={chat.activity} />}
          {chat.is_forum ? (
            <span className={css.fact}>
              <Trans>с темами</Trans>
            </span>
          ) : null}
        </div>
      ) : null}
      {chat.external ? (
        <p className={css.sheetNote}>
          {channel ? (
            <Trans>Этот канал ведёт не Konnekt, правила там свои.</Trans>
          ) : (
            <Trans>Этот чат ведёт не Konnekt: спам там чистим не мы, правила свои.</Trans>
          )}
        </p>
      ) : null}
      <div className={css.actions}>
        <Action onClick={onJoin}>
          {channel ? <Trans>Открыть канал</Trans> : <Trans>Открыть чат</Trans>}
        </Action>
      </div>
      <div className={css.sheetFoot}>
        <Hint>
          <Trans>Откроется в Telegram</Trans>
        </Hint>
      </div>
    </Sheet>
  );
}
