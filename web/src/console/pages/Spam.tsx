import { Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { Hint, Label, SkeletonRows, Sub, Title } from '@/components/Ui';
import { ConsoleFailure, ConsoleGate } from '@/console/ConsoleGate';
import { PingRows, PingSheet } from '@/console/Pings';
import { spamPingsQuery } from '@/console/queries';
import type { SpamPing } from '@/console/session';

/**
 * What the ad detector caught, every chat at once, newest first: the links
 * and handles nobody whitelisted, and who posted them.
 */
export default function ConsoleSpamPage() {
  return (
    <ConsoleGate>
      <Title>
        <Trans>Реклама</Trans>
      </Title>
      <Spam />
    </ConsoleGate>
  );
}

function Spam() {
  const navigate = useNavigate();
  const { data, isPending, error, refetch } = useQuery(spamPingsQuery);
  const [picked, setPicked] = useState<SpamPing | null>(null);

  return (
    <>
      <div style={{ marginTop: 6 }}>
        <Sub>
          <Trans>
            Ссылки и @упоминания, которых нет в белом списке. Детектор только отмечает:
            решает модератор.
          </Trans>
        </Sub>
      </div>
      <Label>
        <Trans>Последние</Trans>
      </Label>
      {isPending ? (
        <SkeletonRows count={5} />
      ) : error || !data ? (
        <ConsoleFailure error={error} retry={() => void refetch()} />
      ) : data.length === 0 ? (
        <Hint>
          <Trans>Детектор ничего не находил.</Trans>
        </Hint>
      ) : (
        <PingRows pings={data} showChat onPick={setPicked} />
      )}
      {picked ? (
        <PingSheet
          key={picked.id}
          ping={picked}
          onClose={() => setPicked(null)}
          // A chat the bot never stored has no screen to open.
          onOpenChat={
            picked.chat_title === null
              ? undefined
              : () => navigate(`/console/chats/${picked.chat_id}`)
          }
        />
      ) : null}
    </>
  );
}
