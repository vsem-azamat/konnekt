/**
 * Short labels for the subject chips on the prices screen.
 *
 * The catalog's names are written for a list ("Теория вероятностей и
 * статистика"); a chip has room for a word or two. By slug, so a subject the
 * catalog renames keeps its chip and one without a label here shows its name.
 */
import { useLingui } from '@lingui/react/macro';

import type { SubjectHintOut } from './generated/types.gen';

export function useSubjectLabel(): (hint: SubjectHintOut) => string {
  const { t } = useLingui();
  const short: Record<string, string> = {
    python: t`Python`,
    'pravdepodobnost-a-statistika': t`Статистика`,
    'cestina-b1': t`Чешский B1`,
    'cestina-b2': t`Чешский B2`,
    anglictina: t`Английский`,
    nemcina: t`Немецкий`,
  };
  return (hint) => short[hint.slug] ?? hint.name;
}
