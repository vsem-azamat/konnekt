import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useLocation, useNavigate } from 'react-router';

import { hapticSelection } from '@/hooks/useTelegram';
import { institutionsQuery } from '@/lib/api';
import { chatPreview } from '@/lib/chatPreview';
import { type Activity, chipFor, initials, type PublicChat, placeOf } from '@/lib/chats';

import { Sheet } from './Sheet';
import { Action, Chevron, Hint, Letters, Row, Tile } from './Ui';
import css from './ui.module.css';

/** Supervisor's word for how much a chat talks, and nothing for `unknown`. */
export function ActivityChip({ activity }: { activity: Activity }) {
  const chip = chipFor(activity);
  if (chip === null) return null;
  return (
    <span
      className={chip === 'busy' ? `${css.activity} ${css.activityBusy}` : css.activity}
    >
      {chip === 'busy' ? (
        <Trans>оживлённый</Trans>
      ) : chip === 'active' ? (
        <Trans>активный</Trans>
      ) : (
        <Trans>тихий</Trans>
      )}
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
export function ChatRow({ chat, tone }: { chat: PublicChat; tone: number }) {
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
          <Tile tone={tone}>
            <Letters text={initials(chat.title)} />
          </Tile>
        }
        title={chat.title}
        hint={
          chipFor(chat.activity) ? <ActivityChip activity={chat.activity} /> : undefined
        }
        trailing={<Chevron />}
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
  // it here, and until it comes the preview simply has no place line.
  const institutions = useQuery(institutionsQuery);
  const place = placeOf(chat, institutions.data ?? []);
  const hasFacts =
    chat.member_count !== null || chipFor(chat.activity) !== null || chat.is_forum;

  return (
    <Sheet
      title={
        <span className={css.chatHead}>
          <Tile tone={tone} large>
            <Letters text={initials(chat.title)} />
          </Tile>
          <span className={css.chatHeadBody}>
            <span>{chat.title}</span>
            {place ? <span className={css.chatPlace}>{place}</span> : null}
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
          <Trans>Этот чат ведут не Konnekt, и правила там свои.</Trans>
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
