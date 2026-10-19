import { Trans } from '@lingui/react/macro';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { ChatIcon, CheckIcon, PersonIcon } from '@/components/icons';
import {
  Action,
  Actions,
  Chevron,
  Hint,
  Row,
  Rows,
  Screen,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { api, rawInitData } from '@/lib/api';
import {
  isSettled,
  type JoinEvent,
  type JoinState,
  joinEventFor,
  joinStart,
  joinStep,
  keepSettled,
  type Settled,
  settledOf,
} from '@/lib/join';

/** Where a settled outcome is kept for this tab's session, per query id. */
const settledKey = (queryId: string) => `join-check:${queryId}`;

function readSettled(queryId: string | null): Settled | null {
  if (!queryId) return null;
  try {
    const value = sessionStorage.getItem(settledKey(queryId));
    return isSettled(value) ? value : null;
  } catch {
    // Storage can be refused (a private window, cleared site data). Then the
    // check opens as new, which is what it was before this existed.
    return null;
  }
}

function writeSettled(queryId: string, outcome: Settled): void {
  try {
    sessionStorage.setItem(
      settledKey(queryId),
      keepSettled(readSettled(queryId), outcome),
    );
  } catch {
    // Nothing to do: see readSettled.
  }
}

/**
 * «Я не бот», for a join request to a moderated chat.
 *
 * Supervisor sends the button; this page proves the person pressing it is the
 * one who asked to join. After it passes it stays open and shows the way on.
 * See catalog/docs/architecture.md, «The join check answers one question».
 */
export default function JoinPage() {
  const [params] = useSearchParams();
  const queryId = params.get('q');
  const [state, setState] = useState<JoinState>(() =>
    joinStart(rawInitData(), queryId, readSettled(queryId)),
  );

  const press = () => {
    const next = joinStep(state, { type: 'press' });
    // The step decides whether anything is sent: the same state back means a
    // request is already out, or the question is settled.
    if (next === state || next.phase !== 'sending') return;
    hapticSelection();
    setState(next);
    // Kept the moment the answer arrives, not after a render: the page may
    // already be gone (the avatar stays tappable), and coming back must show
    // the outcome rather than a button for a spent check.
    const settle = (event: JoinEvent) => {
      const kept = settledOf(joinStep(next, event));
      if (kept) writeSettled(next.queryId, kept);
      setState((current) => joinStep(current, event));
    };
    api.passJoinCheck(next.initData, next.queryId).then(
      () => settle({ type: 'approved' }),
      (error: unknown) => settle(joinEventFor(error)),
    );
  };

  return (
    <Screen>
      <AppHeader />
      <div className={ui.center}>
        {state.phase === 'passed' ? (
          <>
            <Tile tone={0}>
              <CheckIcon size={22} />
            </Tile>
            <Title>
              <Trans>Готово, ты в чате</Trans>
            </Title>
            <Sub>
              <Trans>Можно возвращаться в Telegram.</Trans>
            </Sub>
            <WayOn />
          </>
        ) : state.phase === 'unavailable' ? (
          <>
            <Title>
              <Trans>Открой из заявки</Trans>
            </Title>
            <Sub>
              <Trans>
                Эта проверка открывается кнопкой из заявки на вступление в чат.
              </Trans>
            </Sub>
            <WayOn />
          </>
        ) : state.phase === 'failed' ? (
          <>
            <Title>
              <Trans>Проверка не прошла</Trans>
            </Title>
            <Sub>
              {state.afterRetry ? (
                <Trans>
                  Возможно, первая попытка всё-таки прошла. Проверь чат в Telegram, прежде
                  чем подавать заявку заново.
                </Trans>
              ) : (
                <Trans>
                  Заявка устарела или открыта не тем аккаунтом. Подай её заново.
                </Trans>
              )}
            </Sub>
            <WayOn />
          </>
        ) : (
          <>
            <Tile tone={3}>
              <ChatIcon size={22} />
            </Tile>
            <Title>
              <Trans>Вступление в чат</Trans>
            </Title>
            <Sub>
              <Trans>
                Нажми кнопку, чтобы подтвердить, что ты не бот. Заявка одобрится сразу.
              </Trans>
            </Sub>
            <div className={ui.centerRows}>
              <Actions>
                <Action onClick={press} disabled={state.phase === 'sending'}>
                  {state.phase === 'sending' ? (
                    <Trans>Проверяем…</Trans>
                  ) : (
                    <Trans>Я не бот</Trans>
                  )}
                </Action>
              </Actions>
              {state.phase === 'ready' && state.retried ? (
                <div className={ui.centerNote}>
                  <Hint>
                    <Trans>Не получилось связаться. Попробуй ещё раз.</Trans>
                  </Hint>
                </div>
              ) : null}
            </div>
          </>
        )}
      </div>
    </Screen>
  );
}

/**
 * Where to go from here. Plain pushes: going back shows the settled outcome,
 * kept above, and never a button for a spent check.
 */
function WayOn() {
  const navigate = useNavigate();
  return (
    <div className={ui.centerRows}>
      <Rows>
        <Row
          leading={
            <Tile tone={3}>
              <ChatIcon size={19} />
            </Tile>
          }
          title={<Trans>Студенческие чаты</Trans>}
          hint={<Trans>факультеты, общежития, общие</Trans>}
          trailing={<Chevron />}
          onClick={() => navigate('/chats')}
        />
        <Row
          leading={
            <Tile tone={0}>
              <PersonIcon size={19} />
            </Tile>
          }
          title={<Trans>Помощь с учёбой</Trans>}
          hint={<Trans>репетиторы, вступительные экзамены, нострификация</Trans>}
          trailing={<Chevron />}
          onClick={() => navigate('/')}
        />
      </Rows>
    </div>
  );
}
