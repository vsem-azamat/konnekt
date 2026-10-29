import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { type ReactNode, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  BlockIcon,
  ChatIcon,
  PeopleIcon,
  PersonIcon,
  ShieldIcon,
  TargetIcon,
} from '@/components/icons';
import {
  Action,
  Actions,
  Count,
  Hint,
  Label,
  Row,
  Rows,
  SkeletonRows,
  Sub,
  Tile,
  Title,
} from '@/components/Ui';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import {
  adminCatalogQuery,
  consoleChanges,
  consoleSignalsQuery,
  everyMinute,
} from '@/console/queries';
import css from '@/console/Signals.module.css';
import { utc } from '@/console/session';
import {
  type DecisionProblem,
  decisionProblem,
  elapsed,
  minutesUntil,
  type PendingActionSignal,
  type Signals,
  type WaveSignal,
} from '@/console/signals';

/**
 * What waits for an admin's decision: the waves and the proposed bans the bot
 * asks about in the report chat and in private, then the console's queues.
 * In a browser the menu and the bell count from the same answer.
 */
export default function ConsoleSignalsPage() {
  return (
    <ConsoleGate wide>
      <Title>
        <Trans>Сигналы</Trans>
      </Title>
      <Sub>
        <Trans>Что ждёт решения админа, из чата отчётов и очередей.</Trans>
      </Sub>
      <SignalsBody />
    </ConsoleGate>
  );
}

function SignalsBody() {
  const { t } = useLingui();
  const navigate = useNavigate();
  // The minutes on the cards move on their own; an answer that came back the
  // same would not render them again.
  const now = useNow(30_000);
  // Every minute while open: a browser's shell reads it too, the Mini App has none.
  const signals = useQuery({ ...consoleSignalsQuery, refetchInterval: everyMinute });
  const catalog = useQuery(adminCatalogQuery);
  // A refused press closes its card like a decision does; why stays here,
  // after the card has gone, until it is put away.
  const [refusals, setRefusals] = useState<Refusal[]>([]);
  const refused = (refusal: Refusal) =>
    setRefusals((list) => [...list.filter((item) => item.key !== refusal.key), refusal]);

  if (signals.isPending) return <SkeletonRows count={3} />;
  if (signals.error) {
    return <ConsoleFailure error={signals.error} retry={() => void signals.refetch()} />;
  }

  const { waves, pending_actions: proposals, queues, wave_per_minute } = signals.data;
  const decisions = waves.length + proposals.length;
  const counts = catalog.data?.counts;
  const queueRows: { key: string; count: number; row: (count: number) => ReactNode }[] = [
    {
      key: 'ads',
      count: queues.ads_unreviewed,
      row: (count: number) => (
        <Row
          key="ads"
          leading={
            <Tile tone={1}>
              <ShieldIcon size={19} />
            </Tile>
          }
          title={<Trans>Реклама не разобрана</Trans>}
          hint={<Trans>детектор, все чаты</Trans>}
          trailing={<Count>{count}</Count>}
          onClick={() => navigate('/console/spam')}
        />
      ),
    },
    {
      key: 'review',
      count: queues.chats_in_review,
      row: (count: number) => (
        <Row
          key="review"
          leading={
            <Tile tone={3}>
              <ChatIcon size={19} />
            </Tile>
          }
          title={<Trans>Чаты на проверке</Trans>}
          hint={<Trans>бот в них есть, но они не одобрены</Trans>}
          trailing={<Count>{count}</Count>}
          onClick={() => navigate('/console/chats?tab=decide')}
        />
      ),
    },
    {
      key: 'profiles',
      count: counts?.profiles_to_review ?? 0,
      row: (count: number) => (
        <Row
          key="profiles"
          leading={
            <Tile tone={2}>
              <PersonIcon size={19} />
            </Tile>
          }
          title={<Trans>Новые анкеты</Trans>}
          hint={<Trans>каталог</Trans>}
          trailing={<Count>{count}</Count>}
          onClick={() => navigate('/console/catalog')}
        />
      ),
    },
    {
      key: 'requests',
      count: counts?.unanswered ?? 0,
      row: (count: number) => (
        <Row
          key="requests"
          leading={
            <Tile tone={2}>
              <TargetIcon size={19} />
            </Tile>
          }
          title={<Trans>Заявки без откликов</Trans>}
          hint={<Trans>открытые, срок не вышел</Trans>}
          trailing={<Count>{count}</Count>}
          onClick={() => navigate('/console/catalog')}
        />
      ),
    },
  ].filter((item) => item.count > 0);
  const queued = queueRows.reduce((sum, item) => sum + item.count, 0);

  return (
    <>
      <Label aside={decisions || null}>
        <Trans>Ждут решения</Trans>
      </Label>
      {refusals.map((refusal) => (
        <div key={refusal.key} className={css.refusal} role="status">
          <p>
            <b>{refusal.label}</b>
            <span>
              <ProblemText problem={refusal.problem} />
            </span>
          </p>
          <button
            type="button"
            aria-label={t`Скрыть`}
            onClick={() =>
              setRefusals((list) => list.filter((item) => item.key !== refusal.key))
            }
          >
            ×
          </button>
        </div>
      ))}
      {decisions ? (
        <div className={css.stack}>
          {waves.map((wave) => (
            <WaveCard
              key={`wave-${wave.id}`}
              wave={wave}
              perMinute={wave_per_minute}
              now={now}
              onRefused={refused}
            />
          ))}
          {proposals.map((proposal) => (
            <ProposalCard
              key={`action-${proposal.id}`}
              proposal={proposal}
              now={now}
              onRefused={refused}
            />
          ))}
        </div>
      ) : (
        <Hint>
          <Trans>Ни набегов, ни предложенных банов.</Trans>
        </Hint>
      )}

      <Label aside={queued || null}>
        <Trans>Очереди</Trans>
      </Label>
      {catalog.error ? (
        <ConsoleFailure error={catalog.error} retry={() => void catalog.refetch()} />
      ) : null}
      {queueRows.length ? (
        <Rows>{queueRows.map((item) => item.row(item.count))}</Rows>
      ) : catalog.isPending ? (
        <SkeletonRows count={2} />
      ) : catalog.error ? null : (
        <Hint>
          <Trans>Очереди пусты.</Trans>
        </Hint>
      )}
    </>
  );
}

function WaveCard({
  wave,
  perMinute,
  now,
  onRefused,
}: {
  wave: WaveSignal;
  perMinute: number;
  now: Date;
  onRefused: (refusal: Refusal) => void;
}) {
  const { i18n } = useLingui();
  const title = wave.chat_title ?? String(wave.chat_id);
  const startedAt = new Date(utc(wave.started_at));
  // A wave stays here for a day: yesterday's start says which day it was.
  const started = i18n.date(startedAt, {
    ...(startedAt.toDateString() === now.toDateString()
      ? {}
      : { day: 'numeric', month: 'short' }),
    hour: '2-digit',
    minute: '2-digit',
  });
  const surge = elapsed(wave.last_surge_at, now);
  const ago = surge.unit === 'minutes' ? surge.count : 0;
  const hoursAgo = surge.unit === 'hours' ? surge.count : 0;
  const quiet = minutesUntil(wave.quiet_until, now);
  return (
    <section className={`${css.card} ${css.alert}`}>
      <div className={css.head}>
        <Tile tone={4}>
          <PeopleIcon size={19} />
        </Tile>
        <div>
          <b>
            <Trans>Набег на {title}</Trans>
          </b>
          <span>
            {surge.unit === 'now' ? (
              <Trans>начался {started} · последний всплеск только что</Trans>
            ) : surge.unit === 'minutes' ? (
              <Trans>
                начался {started} · последний всплеск {ago} мин назад
              </Trans>
            ) : (
              <Trans>
                начался {started} · последний всплеск {hoursAgo} ч назад
              </Trans>
            )}
          </span>
        </div>
      </div>
      <p className={css.text}>
        {wave.paused ? (
          <Trans>
            Больше {perMinute} заявок в минуту. Капча на паузе: новым людям бот не пишет,
            в чат никто не вошёл.
          </Trans>
        ) : (
          <Trans>
            Больше {perMinute} заявок в минуту. Пауза закончилась: новые заявки снова
            получают капчу, эти так и ждут.
          </Trans>
        )}
      </p>
      <p className={css.text}>
        <b>
          <Trans>Ждут решения: {wave.held}.</Trans>
        </b>
      </p>
      <dl className={css.facts}>
        <dt>
          <Trans>Чат</Trans>
        </dt>
        <dd>
          {title}
          {wave.member_count !== null ? (
            <>
              {' · '}
              <Plural
                value={wave.member_count}
                one="# участник"
                few="# участника"
                many="# участников"
                other="# участника"
              />
            </>
          ) : null}
        </dd>
        <dt>
          <Trans>Порог</Trans>
        </dt>
        <dd>
          <Trans>{perMinute} заявок в минуту</Trans>
        </dd>
        {wave.paused ? (
          <>
            <dt>
              <Trans>Капча вернётся через</Trans>
            </dt>
            <dd>
              <Trans>{quiet} мин</Trans>
            </dd>
          </>
        ) : null}
      </dl>
      <WaveActions wave={wave} label={title} onRefused={onRefused} />
    </section>
  );
}

function ProposalCard({
  proposal,
  now,
  onRefused,
}: {
  proposal: PendingActionSignal;
  now: Date;
  onRefused: (refusal: Refusal) => void;
}) {
  const who =
    proposal.target_name ??
    (proposal.target_username
      ? `@${proposal.target_username}`
      : String(proposal.target_user_id));
  const chat = proposal.chat_title ?? String(proposal.chat_id);
  const left = minutesUntil(proposal.expires_at, now);
  // The sentence ends with its own full stop.
  const reason = proposal.reason?.trim().replace(/[.!?…]+$/, '');
  return (
    <section className={css.card}>
      <div className={css.head}>
        <Tile tone={1}>
          <BlockIcon size={19} />
        </Tile>
        <div>
          <b>
            {proposal.action === 'blacklist' ? (
              <Trans>Чёрный список: {who}</Trans>
            ) : proposal.chat_id === null ? (
              <Trans>Бан {who} во всех чатах</Trans>
            ) : (
              <Trans>
                Бан {who} в {chat}
              </Trans>
            )}
          </b>
          <span>
            id {proposal.target_user_id}
            {proposal.target_username ? ` · @${proposal.target_username}` : null}
          </span>
        </div>
      </div>
      <p className={css.text}>
        {reason ? (
          <Trans>
            Предложено через MCP: {reason}. Ждёт нажатия админа, истекает через {left}{' '}
            мин.
          </Trans>
        ) : (
          <Trans>
            Предложено через MCP. Ждёт нажатия админа, истекает через {left} мин.
          </Trans>
        )}
      </p>
      <ProposalActions proposal={proposal} label={who} onRefused={onRefused} />
    </section>
  );
}

/**
 * The report chat's three buttons. The answer comes before the work, as the
 * button's does: declining a wave of hundreds takes minutes, and the bot's
 * alert says the outcome when it is done. The card leaves at once; the next
 * reading of the signals agrees.
 */
function WaveActions({
  wave,
  label,
  onRefused,
}: {
  wave: WaveSignal;
  label: string;
  onRefused: (refusal: Refusal) => void;
}) {
  const queryClient = useQueryClient();
  const decide = useMutation({
    mutationFn: (action: 'decline' | 'resume' | 'leave') =>
      consoleChanges.decideWave(wave.id, action),
    onSuccess: () => forget(queryClient, { wave: wave.id }),
    onError: (error) => {
      const problem = decisionProblem(error);
      // Nothing was written; the card stays, with the reason under its buttons.
      if (problem === 'failed') return;
      onRefused({ key: `wave-${wave.id}`, label, problem });
      forget(queryClient, { wave: wave.id });
    },
  });
  return (
    <div className={css.decide}>
      <Actions>
        <Action
          danger
          disabled={decide.isPending}
          onClick={() => decide.mutate('decline')}
        >
          <Trans>Отклонить все</Trans>
        </Action>
        <Action quiet disabled={decide.isPending} onClick={() => decide.mutate('resume')}>
          <Trans>Снять паузу</Trans>
        </Action>
        <Action quiet disabled={decide.isPending} onClick={() => decide.mutate('leave')}>
          <Trans>Пусть висят</Trans>
        </Action>
      </Actions>
      {decide.error ? (
        <Hint>
          <ProblemText problem={decisionProblem(decide.error)} />
        </Hint>
      ) : (
        <Hint>
          <Trans>
            Те же кнопки, что в сообщении бота в чате отчётов; решение видно и там.
          </Trans>
        </Hint>
      )}
    </div>
  );
}

function ProposalActions({
  proposal,
  label,
  onRefused,
}: {
  proposal: PendingActionSignal;
  label: string;
  onRefused: (refusal: Refusal) => void;
}) {
  const queryClient = useQueryClient();
  const decide = useMutation({
    mutationFn: (confirm: boolean) => consoleChanges.decideProposal(proposal.id, confirm),
    onSuccess: () => forget(queryClient, { proposal: proposal.id }),
    onError: (error) => {
      const problem = decisionProblem(error);
      // No answer came back: the press may not have arrived, so the card stays.
      if (problem === 'failed') return;
      // Refused for a reason that will not change: the proposal is closed either way.
      onRefused({ key: `action-${proposal.id}`, label, problem });
      forget(queryClient, { proposal: proposal.id });
    },
  });
  return (
    <div className={css.decide}>
      <Actions>
        <Action danger disabled={decide.isPending} onClick={() => decide.mutate(true)}>
          {proposal.action === 'blacklist' ? (
            <Trans>В чёрный список</Trans>
          ) : (
            <Trans>Подтвердить бан</Trans>
          )}
        </Action>
        <Action quiet disabled={decide.isPending} onClick={() => decide.mutate(false)}>
          <Trans>Отклонить</Trans>
        </Action>
      </Actions>
      {decide.error ? (
        <Hint>
          <ProblemText problem={decisionProblem(decide.error)} />
        </Hint>
      ) : (
        <Hint>
          <Trans>Те же кнопки, что в личном сообщении бота; решение видно и там.</Trans>
        </Hint>
      )}
    </div>
  );
}

/** A press the server refused, kept on screen after its card has gone. */
interface Refusal {
  key: string;
  label: string;
  problem: DecisionProblem;
}

function ProblemText({ problem }: { problem: DecisionProblem }) {
  switch (problem) {
    case 'gone':
      return <Trans>Уже решено в Telegram или срок вышел.</Trans>;
    case 'decided':
      return <Trans>По этой волне уже решили иначе.</Trans>;
    case 'protected':
      return <Trans>Не выполнено: главного администратора забанить нельзя.</Trans>;
    case 'unmanaged':
      return (
        <Trans>Не выполнено: бот больше не модерирует этот чат. Запрос закрыт.</Trans>
      );
    case 'refused':
      return <Trans>Не выполнено: Telegram отказал. Запрос закрыт.</Trans>;
    default:
      return <Trans>Не получилось связаться с сервером. Попробуйте ещё раз.</Trans>;
  }
}

/** Take a decided card off the screen and the counters without waiting for the next reading. */
function forget(
  queryClient: ReturnType<typeof useQueryClient>,
  decided: { wave: number } | { proposal: number },
) {
  queryClient.setQueryData<Signals>(consoleSignalsQuery.queryKey, (old) =>
    old
      ? 'wave' in decided
        ? { ...old, waves: old.waves.filter((wave) => wave.id !== decided.wave) }
        : {
            ...old,
            pending_actions: old.pending_actions.filter(
              (proposal) => proposal.id !== decided.proposal,
            ),
          }
      : old,
  );
}

/** The time now, read again every `ms` while the screen is open. */
function useNow(ms: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), ms);
    return () => clearInterval(timer);
  }, [ms]);
  return now;
}
