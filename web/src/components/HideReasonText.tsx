import { Trans } from '@lingui/react/macro';

import type { HideReason } from '@/lib/types';

/**
 * Why an operator hid a profile, in words: the console picks it, and the
 * owner reads the same words in «Моя анкета». «Другое» is shown as the
 * operator's own note instead, by whoever renders it.
 */
export function HideReasonText({ reason }: { reason: HideReason }) {
  switch (reason) {
    case 'spam':
      return <Trans>Реклама или спам</Trans>;
    case 'misleading':
      return <Trans>Неправдивые сведения</Trans>;
    case 'rules':
      return <Trans>Нарушает правила</Trans>;
    case 'other':
      return <Trans>Другое</Trans>;
  }
}

export const HIDE_REASONS: readonly HideReason[] = [
  'spam',
  'misleading',
  'rules',
  'other',
];
