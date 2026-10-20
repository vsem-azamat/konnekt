import { useLingui } from '@lingui/react/macro';

import type { AudienceStatus, Touchpoint } from '@/console/audience';

/** The words for the audience's statuses and touchpoints, shared by its screens. */
export function useAudienceLabels(): {
  status: Record<AudienceStatus, string>;
  touchpoint: Record<Touchpoint, string>;
} {
  const { t } = useLingui();
  return {
    status: {
      reachable: t`можно написать`,
      never_started: t`не запускали бота`,
      blocked: t`заблокировали`,
      opted_out: t`отписались`,
    },
    touchpoint: {
      main_bot: t`Бот`,
      mini_app: t`Mini App`,
      contact_bot: t`Бот связи`,
      moved_bot: t`Старые боты`,
    },
  };
}
