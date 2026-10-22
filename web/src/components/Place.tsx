/**
 * Cities and chat topics, in the reader's language.
 *
 * A city arrives as the catalog's taxonomy spells it, in Czech («Praha»). The
 * cities the taxonomy has universities in are translated here; any other is
 * shown as it came, which is still its real name.
 */

import { Trans, useLingui } from '@lingui/react/macro';
import type { ReactElement } from 'react';

import type { Topic } from '@/lib/chats';

/**
 * The cities with a name in the reader's language, keyed by the Czech one.
 *
 * Also what a city typed into the request sheet is matched against, so the
 * feed gets «Ostrava» whichever spelling was typed.
 */
export function useCityNames(): Record<string, string> {
  const { t } = useLingui();
  return {
    Praha: t`Прага`,
    Brno: t`Брно`,
    Ostrava: t`Острава`,
    Plzeň: t`Пльзень`,
    Olomouc: t`Оломоуц`,
    Liberec: t`Либерец`,
    'České Budějovice': t`Ческе-Будеёвице`,
    Pardubice: t`Пардубице`,
    'Hradec Králové': t`Градец-Кралове`,
    Zlín: t`Злин`,
  };
}

/** A city's name, or «вся Чехия» for a chat that is for every city. */
export function CityName({ city }: { city: string | null }): ReactElement {
  const names = useCityNames();
  if (city === null) return <Trans>вся Чехия</Trans>;
  return <>{names[city] ?? city}</>;
}

/** A heading of the catalogue. */
export function TopicHeading({ topic }: { topic: Topic }): ReactElement {
  switch (topic) {
    case 'university':
      return <Trans>Вузы</Trans>;
    case 'subjects':
      return <Trans>Предметы</Trans>;
    case 'dorms':
      return <Trans>Общежития</Trans>;
    case 'work_it':
      return <Trans>Работа и IT</Trans>;
    case 'general':
      return <Trans>Общее</Trans>;
  }
}

/** What one chat is, in a chat's preview: «предмет · вся Чехия». */
export function TopicWord({ topic }: { topic: Topic }): ReactElement {
  switch (topic) {
    case 'university':
      return <Trans>вуз</Trans>;
    case 'subjects':
      return <Trans>предмет</Trans>;
    case 'dorms':
      return <Trans>общежитие</Trans>;
    case 'work_it':
      return <Trans>работа и IT</Trans>;
    case 'general':
      return <Trans>общий чат</Trans>;
  }
}
