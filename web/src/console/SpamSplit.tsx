import { Trans, useLingui } from '@lingui/react/macro';
import { type ReactNode, useSyncExternalStore } from 'react';

import { Action, Actions, Hint, Label, ui } from '@/components/Ui';
import { ChatFace, Handle, PersonFace } from '@/console/Faces';
import css from '@/console/Spam.module.css';
import { personName, type SpamPing, type SpamVerdict, utc } from '@/console/session';
import { awaitsAnswer, byDay } from '@/console/spam';

const WIDE = '(min-width: 1100px)';

/** A window wide enough for the queue beside the hit it shows. */
export function useWideWindow(): boolean {
  return useSyncExternalStore(
    (change) => {
      const query = matchMedia(WIDE);
      query.addEventListener('change', change);
      return () => query.removeEventListener('change', change);
    },
    () => matchMedia(WIDE).matches,
    () => false,
  );
}

/**
 * The queue as a mail client shows it: the hits on the left, the one picked on
 * the right with its author, its chat, the whole message and the answers.
 */
export function SpamSplit({
  pings,
  selected,
  showChat,
  busy,
  more,
  onSelect,
  onBan,
  onReview,
  onOpenChat,
  dayName,
}: {
  pings: SpamPing[];
  selected: SpamPing;
  showChat: boolean;
  busy: boolean;
  more: ReactNode;
  onSelect: (ping: SpamPing) => void;
  onBan: (ping: SpamPing) => void;
  onReview: (ping: SpamPing, verdict: Exclude<SpamVerdict, 'ad'>) => void;
  onOpenChat: (ping: SpamPing) => void;
  dayName: (day: string) => ReactNode;
}) {
  const { t, i18n } = useLingui();
  const time = (ping: SpamPing) =>
    i18n.date(utc(ping.detected_at), { hour: '2-digit', minute: '2-digit' });
  const kind = (ping: SpamPing) =>
    ping.kind === 'link' ? t`ссылка` : ping.kind === 'mention' ? t`упоминание` : null;
  return (
    <div className={css.split}>
      <div className={css.list}>
        {byDay(pings).map((group) => (
          <div key={group.day}>
            <Label aside={group.pings.length}>{dayName(group.day)}</Label>
            <div className={css.lines}>
              {group.pings.map((ping) => (
                <button
                  key={ping.id}
                  type="button"
                  className={
                    ping.id === selected.id ? `${css.line} ${css.lineOn}` : css.line
                  }
                  aria-current={ping.id === selected.id}
                  onClick={() => onSelect(ping)}
                >
                  <PersonFace person={ping} size={32} />
                  <span className={css.lineBody}>
                    <span className={css.lineTop}>
                      <b>{personName(ping)}</b>
                      <span>{time(ping)}</span>
                    </span>
                    {showChat ? (
                      <span className={css.lineChat}>
                        <ChatFace
                          chat={{ id: ping.chat_id, title: ping.chat_title }}
                          size={16}
                        />
                        <span>{ping.chat_title ?? ping.chat_id}</span>
                      </span>
                    ) : null}
                    <span className={css.lineText}>
                      {ping.snippet ?? ping.matches.join(', ')}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
        {more}
      </div>

      <section className={css.panel} aria-label={t`Выбранный случай`}>
        <div className={css.panelWho}>
          <PersonFace person={selected} size={56} />
          <span className={css.panelWhoText}>
            <b>{personName(selected)}</b>
            <Handle person={selected} />
          </span>
          <span className={css.panelWhen}>
            {kind(selected) ? (
              <span className={ui.pingCardKind}>{kind(selected)}</span>
            ) : null}
            {time(selected)}
          </span>
        </div>
        <div className={css.panelChat}>
          <ChatFace
            chat={{ id: selected.chat_id, title: selected.chat_title }}
            size={24}
          />
          <b>{selected.chat_title ?? selected.chat_id}</b>
          {selected.chat_title !== null ? (
            <button
              type="button"
              className={ui.inlineLink}
              onClick={() => onOpenChat(selected)}
            >
              <Trans>Открыть чат ›</Trans>
            </button>
          ) : null}
        </div>
        {selected.snippet ? (
          <blockquote className={`${ui.quote} ${css.panelText}`}>
            {selected.snippet}
          </blockquote>
        ) : null}
        <Hint>{selected.matches.join(', ')}</Hint>
        {awaitsAnswer(selected) ? (
          <Actions>
            <Action disabled={busy} onClick={() => onBan(selected)}>
              <Trans>Забанить</Trans>
            </Action>
            <Action quiet disabled={busy} onClick={() => onReview(selected, 'not_ad')}>
              <Trans>Не реклама</Trans>
            </Action>
            <Action quiet disabled={busy} onClick={() => onReview(selected, 'done')}>
              <Trans>Разобрано</Trans>
            </Action>
          </Actions>
        ) : (
          <Hint>
            {selected.verdict === 'not_ad' ? (
              <Trans>Не реклама</Trans>
            ) : selected.verdict === 'done' ? (
              <Trans>Разобрано</Trans>
            ) : (
              <Trans>Автор забанен</Trans>
            )}
          </Hint>
        )}
      </section>
    </div>
  );
}
