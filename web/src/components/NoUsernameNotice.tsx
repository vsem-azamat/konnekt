import { Trans } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';

import { ui } from '@/components/Ui';
import { meQuery } from '@/lib/api';

/**
 * Students write to a helper through the helper's public @username, so without
 * one the card has no «Написать» and a response cannot be sent. Read again on
 * every open: a username can be removed at any time. It warns and never
 * blocks: a profile without one is still worth publishing.
 */
export function NoUsernameNotice() {
  const { data: me } = useQuery({ ...meQuery, refetchOnMount: 'always' });
  if (!me || me.username) return null;
  return (
    <div className={ui.notice} role="note">
      <span className={ui.noticeTitle}>
        <Trans>Заведи в Telegram публичный @username — иначе тебе не ответят</Trans>
      </span>
      <span>
        <Trans>Telegram → Настройки → Имя пользователя</Trans>
      </span>
    </div>
  );
}
