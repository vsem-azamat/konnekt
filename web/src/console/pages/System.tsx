import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { Sheet } from '@/components/Sheet';
import {
  Action,
  Count,
  Hint,
  Label,
  Row,
  Rows,
  SkeletonRows,
  Sub,
  Title,
  ui,
} from '@/components/Ui';
import { useBrowserConsole } from '@/console/browserContext';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { consoleChanges, consoleSystemQuery, sessionsQuery } from '@/console/queries';
import { type AdminSession, utc } from '@/console/session';

/**
 * Where the console is signed in, and whether the moving parts are there:
 * the bot that sends, the switches that come from configuration.
 */
export default function ConsoleSystemPage() {
  return (
    <ConsoleGate>
      <Title>
        <Trans>Система</Trans>
      </Title>
      <System />
    </ConsoleGate>
  );
}

/** A browser from its user agent, roughly: enough to tell two sessions apart. */
function device(agent: string | null): string {
  if (!agent) return '—';
  if (/Telegram/i.test(agent)) return 'Telegram';
  if (/iPhone|iPad/i.test(agent)) return 'iOS';
  if (/Android/i.test(agent)) return 'Android';
  if (/Mac OS/i.test(agent)) return 'macOS';
  if (/Windows/i.test(agent)) return 'Windows';
  if (/Linux/i.test(agent)) return 'Linux';
  return agent.slice(0, 24);
}

function System() {
  const { t, i18n } = useLingui();
  const queryClient = useQueryClient();
  const system = useQuery(consoleSystemQuery);
  const sessions = useQuery(sessionsQuery);
  const [picked, setPicked] = useState<AdminSession | null>(null);
  const closeSession = useMutation({
    mutationFn: (session: AdminSession) => consoleChanges.closeSession(session.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: sessionsQuery.queryKey });
      setPicked(null);
    },
  });
  const when = (iso: string) =>
    i18n.date(utc(iso), {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  const inBrowser = useBrowserConsole();
  const signOut = useMutation({
    mutationFn: consoleChanges.signOut,
    // Out of the console: in Telegram it would sign straight back in; a browser
    // goes to the sign-in page.
    onSuccess: () => window.location.assign(inBrowser ? '/login' : '/'),
  });
  const dismiss = () => {
    closeSession.reset();
    signOut.reset();
    setPicked(null);
  };

  return (
    <>
      <Label>
        <Trans>Состояние</Trans>
      </Label>
      {system.isPending ? (
        <SkeletonRows count={2} />
      ) : system.error || !system.data ? (
        <ConsoleFailure error={system.error} retry={() => void system.refetch()} />
      ) : (
        <Rows>
          <Row
            title={<Trans>Бот для действий из консоли</Trans>}
            hint={
              system.data.publish_bot_ready ? (
                <Trans>на месте: баны и обновления из Telegram работают</Trans>
              ) : (
                <Trans>не настроен: баны и обновления из Telegram не пройдут</Trans>
              )
            }
            trailing={<Count>{system.data.publish_bot_ready ? '✓' : '—'}</Count>}
          />
          <Row
            title={<Trans>Главные администраторы</Trans>}
            trailing={<Count>{system.data.super_admin_ids.length}</Count>}
          />
          <Row
            title={<Trans>Вход действует</Trans>}
            trailing={
              <Count>
                <Plural
                  value={system.data.session_ttl_days}
                  one="# день"
                  few="# дня"
                  many="# дней"
                  other="# дня"
                />
              </Count>
            }
          />
          {system.data.feature_flags.map((flag) => (
            <Row
              key={flag.name}
              title={flag.name}
              hint={flag.source}
              trailing={<Count>{flag.enabled ? t`вкл.` : t`выкл.`}</Count>}
            />
          ))}
        </Rows>
      )}

      <Label>
        <Trans>Где выполнен вход</Trans>
      </Label>
      {sessions.isPending ? (
        <SkeletonRows count={2} />
      ) : sessions.error || !sessions.data ? (
        <ConsoleFailure error={sessions.error} retry={() => void sessions.refetch()} />
      ) : (
        <Rows>
          {sessions.data.map((session) => (
            <Row
              key={session.id}
              title={
                <>
                  {device(session.user_agent)}
                  {session.is_current ? (
                    <>
                      {' · '}
                      <Trans>это устройство</Trans>
                    </>
                  ) : null}
                </>
              }
              hint={
                <Trans>
                  был {when(session.last_seen_at)} · {session.ip ?? '—'}
                </Trans>
              }
              onClick={() => setPicked(session)}
            />
          ))}
        </Rows>
      )}

      {picked?.is_current ? (
        // This device's own session is ended by signing out, not by closing it
        // from the list, which webapi refuses.
        <Sheet
          title={t`Выйти на этом устройстве?`}
          closeLabel={t`Отмена`}
          onClose={dismiss}
        >
          <Sub>
            <Trans>Консоль снова откроется из Telegram.</Trans>
          </Sub>
          {signOut.isError ? (
            <Hint>
              <Trans>Не получилось. Попробуйте ещё раз.</Trans>
            </Hint>
          ) : null}
          <div className={ui.actionsStacked}>
            <Action disabled={signOut.isPending} onClick={() => signOut.mutate()}>
              <Trans>Выйти</Trans>
            </Action>
            <Action quiet onClick={dismiss}>
              <Trans>Отмена</Trans>
            </Action>
          </div>
        </Sheet>
      ) : picked ? (
        <Sheet title={t`Закрыть этот вход?`} closeLabel={t`Отмена`} onClose={dismiss}>
          <Sub>
            {device(picked.user_agent)} · {picked.ip ?? '—'}
          </Sub>
          {closeSession.isError ? (
            <Hint>
              <Trans>Не получилось. Попробуйте ещё раз.</Trans>
            </Hint>
          ) : null}
          <div className={ui.actionsStacked}>
            <Action
              disabled={closeSession.isPending}
              onClick={() => closeSession.mutate(picked)}
            >
              <Trans>Закрыть</Trans>
            </Action>
            <Action quiet onClick={dismiss}>
              <Trans>Отмена</Trans>
            </Action>
          </div>
        </Sheet>
      ) : null}
    </>
  );
}
