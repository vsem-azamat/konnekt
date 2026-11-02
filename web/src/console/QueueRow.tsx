import { Plural, Trans } from '@lingui/react/macro';
import type { ReactNode } from 'react';
import { ChatIcon, PersonIcon, ShieldIcon, TargetIcon } from '@/components/icons';
import { Count, Row, Tile } from '@/components/Ui';
import { type Queue, type QueueKey, waited } from '@/console/signals';

/** Where each queue is worked through, and how its row looks. */
const QUEUES: Record<
  QueueKey,
  { path: string; tile: ReactNode; title: ReactNode; hint: ReactNode }
> = {
  ads: {
    path: '/console/spam',
    tile: (
      <Tile tone={1}>
        <ShieldIcon size={19} />
      </Tile>
    ),
    title: <Trans>Реклама не разобрана</Trans>,
    hint: <Trans>детектор, все чаты</Trans>,
  },
  review: {
    path: '/console/chats?tab=decide',
    tile: (
      <Tile tone={3}>
        <ChatIcon size={19} />
      </Tile>
    ),
    title: <Trans>Чаты на проверке</Trans>,
    hint: <Trans>бот в них есть, но они не одобрены</Trans>,
  },
  profiles: {
    path: '/console/catalog',
    tile: (
      <Tile tone={2}>
        <PersonIcon size={19} />
      </Tile>
    ),
    title: <Trans>Новые анкеты</Trans>,
    hint: <Trans>каталог</Trans>,
  },
  requests: {
    path: '/console/catalog',
    tile: (
      <Tile tone={2}>
        <TargetIcon size={19} />
      </Tile>
    ),
    title: <Trans>Заявки без откликов</Trans>,
    hint: <Trans>открытые, срок не вышел</Trans>,
  },
};

/**
 * A queue on the summary and on Сигналы: how many wait, and how long the
 * oldest has. The wait goes first, since a narrow row cuts the hint's end.
 */
export function QueueRow({
  queue,
  now,
  onOpen,
}: {
  queue: Queue;
  now: Date;
  onOpen: (path: string) => void;
}) {
  const { path, tile, title, hint } = QUEUES[queue.key];
  return (
    <Row
      leading={tile}
      title={title}
      hint={
        queue.since ? (
          <>
            <Waited since={queue.since} alone={queue.count === 1} now={now} /> · {hint}
          </>
        ) : (
          hint
        )
      }
      trailing={<Count>{queue.count}</Count>}
      onClick={() => onOpen(path)}
    />
  );
}

/** «ждут до N»: the oldest waits N, the others less; one alone just waits. */
function Waited({ since, alone, now }: { since: string; alone: boolean; now: Date }) {
  const wait = waited(since, now);
  if (wait.unit === 'fresh') {
    return alone ? <Trans>ждёт меньше часа</Trans> : <Trans>ждут меньше часа</Trans>;
  }
  if (wait.unit === 'hours') {
    return alone ? (
      <Trans>
        ждёт{' '}
        <Plural
          value={wait.count}
          one="# час"
          few="# часа"
          many="# часов"
          other="# часа"
        />
      </Trans>
    ) : (
      <Trans>
        ждут до{' '}
        <Plural
          value={wait.count}
          one="# часа"
          few="# часов"
          many="# часов"
          other="# часа"
        />
      </Trans>
    );
  }
  return alone ? (
    <Trans>
      ждёт{' '}
      <Plural value={wait.count} one="# день" few="# дня" many="# дней" other="# дня" />
    </Trans>
  ) : (
    <Trans>
      ждут до{' '}
      <Plural value={wait.count} one="# дня" few="# дней" many="# дней" other="# дня" />
    </Trans>
  );
}
