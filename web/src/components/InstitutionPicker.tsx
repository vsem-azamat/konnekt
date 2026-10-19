import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { SearchIcon } from '@/components/icons';
import { Hint, Row, Rows, ui } from '@/components/Ui';
import { institutionsQuery } from '@/lib/api';
import { pickable } from '@/lib/institutions';
import type { Institution } from '@/lib/types';

/**
 * Which school, for the one kind of help that is about a particular one.
 *
 * `entrance_prep` is the only service type with `requires_institution`, and
 * until now nothing asked: the flag was read by no screen, so preparation for
 * ČVUT's entrance exam was stored the same way as preparation for nobody's.
 *
 * Filtered here rather than on the server, unlike subjects. The whole list is
 * sixteen universities and their 119 faculties — reference data that changes
 * about never — so it is one request, cached for an hour, and every keystroke
 * after it is free. Subjects go to the server because there are hundreds of
 * them and the match has to be fuzzy across four languages; a school is matched
 * on its own name, its abbreviation and its university's, in either script
 * («чвут», «масарик»), which lib/institutions.ts does on the client.
 *
 * `taken` is not politeness: `offers` is unique on its four axes, so a second
 * row for the same school is a 422 the screen can only report as "did not
 * save".
 */
export function InstitutionPicker({
  onPick,
  taken,
  placeholder,
}: {
  onPick: (institution: Institution) => void;
  /** Ids already on the offer, so the list does not offer them again. */
  taken: Set<number>;
  placeholder?: string;
}) {
  const { t } = useLingui();
  const [query, setQuery] = useState('');

  const { data, isError, isPending } = useQuery(institutionsQuery);

  const needle = query.trim();
  const found = useMemo(() => pickable(data ?? [], needle, taken), [data, needle, taken]);

  return (
    <>
      <div className={ui.field}>
        <SearchIcon size={18} className={ui.fieldIcon} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={placeholder ?? t`Вуз или факультет — ČVUT, VŠE, FEL`}
          maxLength={120}
          style={{ all: 'unset', flex: 1, minWidth: 0 }}
        />
      </div>
      {/* A search box that answers nothing looks like a school nobody has
          heard of. The list is one request, and when it fails every query comes
          back empty with nothing to explain it. */}
      {isError ? (
        <Hint>
          <Trans>Список вузов не загрузился. Попробуй ещё раз позже.</Trans>
        </Hint>
      ) : isPending && query.trim().length >= 2 ? (
        <Hint>
          <Trans>Загружаем список вузов…</Trans>
        </Hint>
      ) : null}
      {/* No margin of its own: the card this sits in spaces everything in it,
          the way it does for the subject search. */}
      {needle.length >= 2 && !isPending && !isError && found.length === 0 ? (
        <Hint>
          <Trans>Ничего не нашли. Попробуй сокращение — ČVUT, VŠE, MUNI.</Trans>
        </Hint>
      ) : null}
      {found.length > 0 ? (
        <Rows>
          {found.map(({ row, under }) => (
            <Row
              key={row.id}
              title={row.short_name ?? row.name}
              hint={under ?? row.name}
              onClick={() => {
                onPick(row);
                setQuery('');
              }}
            />
          ))}
        </Rows>
      ) : null}
    </>
  );
}
