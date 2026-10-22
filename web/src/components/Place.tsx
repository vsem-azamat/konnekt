/**
 * Cities and chat topics, in the reader's language.
 *
 * A city arrives as the catalog's taxonomy spells it, in Czech («Praha»). The
 * cities the taxonomy has universities in are translated here; any other is
 * shown as it came, which is still its real name.
 */

import { Trans } from '@lingui/react/macro';
import type { ReactElement } from 'react';

import type { Topic } from '@/lib/chats';

/** A city's name, or «вся Чехия» for a chat that is for every city. */
export function CityName({ city }: { city: string | null }): ReactElement {
  switch (city) {
    case null:
      return <Trans>вся Чехия</Trans>;
    case 'Praha':
      return <Trans>Прага</Trans>;
    case 'Brno':
      return <Trans>Брно</Trans>;
    case 'Ostrava':
      return <Trans>Острава</Trans>;
    case 'Plzeň':
      return <Trans>Пльзень</Trans>;
    case 'Olomouc':
      return <Trans>Оломоуц</Trans>;
    case 'Liberec':
      return <Trans>Либерец</Trans>;
    case 'České Budějovice':
      return <Trans>Ческе-Будеёвице</Trans>;
    case 'Pardubice':
      return <Trans>Пардубице</Trans>;
    case 'Hradec Králové':
      return <Trans>Градец-Кралове</Trans>;
    case 'Zlín':
      return <Trans>Злин</Trans>;
    default:
      return <>{city}</>;
  }
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
