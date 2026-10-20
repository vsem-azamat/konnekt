import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Sheet } from '@/components/Sheet';
import { Action, Hint, Row, Rows, Sub, ui } from '@/components/Ui';
import { BanOutcomeSheet, BanSheet } from '@/console/BanSheet';
import { type BanOutcome, banOutcome } from '@/console/ban';
import { FailureText } from '@/console/FailureText';
import {
  blockedQuery,
  consoleChanges,
  consoleStatsQuery,
  consoleSystemQuery,
} from '@/console/queries';
import { personName, type SpamPing, utc } from '@/console/session';
import { hapticSelection } from '@/hooks/useTelegram';

/**
 * Ad-detector hits as rows: who, what they linked to, and where. The chat is
 * named only where the list mixes chats.
 */
export function PingRows({
  pings,
  showChat,
  onPick,
}: {
  pings: SpamPing[];
  showChat: boolean;
  onPick: (ping: SpamPing) => void;
}) {
  const { t, i18n } = useLingui();
  const when = (iso: string) =>
    i18n.date(utc(iso), {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  return (
    <Rows>
      {pings.map((ping) => (
        <Row
          key={ping.id}
          title={
            <>
              {personName(ping)}
              {ping.blocked ? ` · ${t`заблокирован`}` : null}
            </>
          }
          hint={[
            ping.matches.join(', '),
            showChat ? (ping.chat_title ?? String(ping.chat_id)) : null,
            when(ping.detected_at),
          ]
            .filter(Boolean)
            .join(' · ')}
          onClick={() => {
            hapticSelection();
            onPick(ping);
          }}
        />
      ))}
    </Rows>
  );
}

/**
 * One hit up close: the message as the bot saw it, and the ban that answers
 * it, asked in a sheet of its own (see BanSheet).
 */
export function PingSheet({
  ping,
  onClose,
  onOpenChat,
  banFirst = false,
}: {
  ping: SpamPing;
  onClose: () => void;
  onOpenChat?: () => void;
  /** Straight to the ban, as a queue card asks; «Отмена» then closes it. */
  banFirst?: boolean;
}) {
  const { t } = useLingui();
  const queryClient = useQueryClient();
  const system = useQuery(consoleSystemQuery);
  const admin = system.data?.super_admin_ids.includes(ping.user_id) ?? false;
  const ban = useMutation({
    mutationFn: (revoke: boolean) => consoleChanges.block(ping.user_id, revoke),
    onSuccess: (answer) => {
      void queryClient.invalidateQueries({ queryKey: ['console', 'spam'] });
      void queryClient.invalidateQueries({ queryKey: ['console', 'chat'] });
      void queryClient.invalidateQueries({ queryKey: blockedQuery.queryKey });
      void queryClient.invalidateQueries({ queryKey: consoleStatsQuery.queryKey });
      const outcome = banOutcome(answer);
      if (outcome === 'done') onClose();
      else setOutcome({ outcome, failed: answer.failed_chats.length });
    },
  });
  const [banning, setBanning] = useState(banFirst);
  const [outcome, setOutcome] = useState<{
    outcome: Exclude<BanOutcome, 'done'>;
    failed: number;
  } | null>(null);
  const close = () => {
    ban.reset();
    onClose();
  };

  if (outcome !== null) {
    return <BanOutcomeSheet name={personName(ping)} {...outcome} onClose={close} />;
  }
  // Listed and the hit still waiting is a ban that took nowhere: on offer again.
  const bannable = !admin && (!ping.blocked || ping.verdict === null);
  // Nobody to ban is the hit's own sheet, which says why.
  if (banning && bannable) {
    return (
      <BanSheet
        name={personName(ping)}
        busy={ban.isPending}
        error={ban.error ? <FailureText error={ban.error} /> : null}
        onBan={(revoke) => ban.mutate(revoke)}
        // Back to the hit it was asked from, not out of both.
        onClose={
          banFirst
            ? close
            : () => {
                ban.reset();
                setBanning(false);
              }
        }
      />
    );
  }

  return (
    <Sheet title={t`Реклама`} closeLabel={t`Отмена`} onClose={close}>
      <Sub>
        {personName(ping)}
        {ping.username && personName(ping) !== `@${ping.username}`
          ? ` · @${ping.username}`
          : null}
        {' · '}
        {ping.chat_title ?? ping.chat_id}
      </Sub>
      {ping.snippet ? <blockquote className={ui.quote}>{ping.snippet}</blockquote> : null}
      <Hint>{ping.matches.join(', ')}</Hint>
      <div className={ui.actionsStacked}>
        {!bannable && ping.blocked ? (
          <Hint>
            <Trans>Уже в чёрном списке.</Trans>
          </Hint>
        ) : admin ? (
          <Hint>
            <Trans>Это главный администратор.</Trans>
          </Hint>
        ) : (
          <Action onClick={() => setBanning(true)}>
            <Trans>Забанить…</Trans>
          </Action>
        )}
        {onOpenChat ? (
          <Action quiet onClick={onOpenChat}>
            <Trans>Открыть чат</Trans>
          </Action>
        ) : null}
        <Action quiet onClick={close}>
          <Trans>Отмена</Trans>
        </Action>
      </div>
    </Sheet>
  );
}
