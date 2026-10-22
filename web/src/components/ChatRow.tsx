import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import type { ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { hapticSelection } from '@/hooks/useTelegram';
import { institutionsQuery } from '@/lib/api';
import { chatPreview } from '@/lib/chatPreview';
import {
  type Activity,
  chipFor,
  initials,
  type PublicChat,
  placeOf,
  rowDotFor,
} from '@/lib/chats';
import { PersonIcon } from './icons';
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
 */
export function Members({
  count,
  activity,
}: {
  count: number | null;
  activity: Activity;
}) {
  const { i18n } = useLingui();
  const dot = rowDotFor(activity);
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
              <Plural
                value={count}
                one="участник"
                few="участника"
                many="участников"
                other="участника"
              />
            </span>
          </>
        )}
        {chipFor(activity) ? (
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
export function ChatTitle({ title, external }: { title: string; external: boolean }) {
  if (!external) return <>{title}</>;
  return (
    <span className={css.nameLine}>
      <span className={css.name}>{title}</span>
      <NotOurs />
      <span className={css.srOnly}>
        {', '}
        <Trans>не наш чат</Trans>
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
    openLink: openTelegramLink,
    // react-router keeps a location's state under `usr` in the history entry,
    // and writes it there synchronously on navigate.
    stateNow: () => (window.history.state as { usr?: unknown } | null)?.usr,
  });
  return (
    <>
      <Row
        leading={
          <Tile tone={tone} round photo={chat.avatar}>
            <Letters text={initials(chat.title)} />
          </Tile>
        }
        title={<ChatTitle title={chat.title} external={chat.external} />}
        hint={hint}
        trailing={
          <>
            <Members count={chat.member_count} activity={chat.activity} />
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
  const hasFacts =
    chat.member_count !== null || chipFor(chat.activity) !== null || chat.is_forum;

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
              {chat.external ? (
                <span className={css.srOnly}>
                  {', '}
                  <Trans>не наш чат</Trans>
                </span>
              ) : null}
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
              <Plural
                value={chat.member_count}
                one="# участник"
                few="# участника"
                many="# участников"
                other="# участника"
              />
            </span>
          ) : null}
          <ActivityChip activity={chat.activity} />
          {chat.is_forum ? (
            <span className={css.fact}>
              <Trans>с темами</Trans>
            </span>
          ) : null}
        </div>
      ) : null}
      {chat.external ? (
        <p className={css.sheetNote}>
          <Trans>Этот чат ведёт не Konnekt: спам там чистим не мы, правила свои.</Trans>
        </p>
      ) : null}
      <div className={css.actions}>
        <Action onClick={onJoin}>
          <Trans>Открыть чат</Trans>
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
