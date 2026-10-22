import { Plural, Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
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
import { adminCatalogQuery, consoleSignalsQuery } from '@/console/queries';
import css from '@/console/Signals.module.css';
import { utc } from '@/console/session';
import {
  elapsed,
  minutesUntil,
  type PendingActionSignal,
  type WaveSignal,
} from '@/console/signals';

/**
 * What waits for an admin's decision: the waves and the proposed bans the bot
 * asks about in the report chat and in private, then the console's queues.
 * The browser's only; the menu and the bell count from the same answer.
 */
export default function ConsoleSignalsPage() {
  return (
    <ConsoleGate>
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
  const navigate = useNavigate();
  // The minutes on the cards move on their own; an answer that came back the
  // same would not render them again.
  const now = useNow(30_000);
  // The shell reads both every minute; this screen shares its answers.
  const signals = useQuery(consoleSignalsQuery);
  const catalog = useQuery(adminCatalogQuery);

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
          onClick={() => navigate('/console/chats?status=discovered')}
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
      {decisions ? (
        <div className={css.stack}>
          {waves.map((wave) => (
            <WaveCard
              key={`wave-${wave.id}`}
              wave={wave}
              perMinute={wave_per_minute}
              now={now}
            />
          ))}
          {proposals.map((proposal) => (
            <ProposalCard key={`action-${proposal.id}`} proposal={proposal} now={now} />
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
}: {
  wave: WaveSignal;
  perMinute: number;
  now: Date;
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
      <Hint>
        <Trans>Решают кнопками в сообщении бота в чате отчётов.</Trans>
      </Hint>
    </section>
  );
}

function ProposalCard({ proposal, now }: { proposal: PendingActionSignal; now: Date }) {
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
      <Hint>
        <Trans>Подтвердить или отклонить можно в личном сообщении бота.</Trans>
      </Hint>
    </section>
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
