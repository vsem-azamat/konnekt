import { useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { SearchIcon } from '@/components/icons';
import { Row, Rows, ui } from '@/components/Ui';
import { api } from '@/lib/api';
import type { Subject } from '@/lib/types';

/**
 * Find a subject by typing.
 *
 * Fuzzy on the server, so "matan" and "матан" both land on the same node —
 * which is the whole reason this is a search box and not a tree to browse.
 *
 * Lifted out of the cabinet when the offer flow needed it. The cabinet has
 * since stopped searching subjects itself — adding a service goes through the
 * grid — so `OfferPrices` is the only caller today. It stays here rather than
 * moving into that page because the next screen that lets someone name a
 * subject will want the same debounce, the same minimum length, and the same
 * idea of what counts as already taken.
 *
 * It brings no spacing of its own — no margin above the results, nothing after
 * the box — because a caller that stacks it with a rule of its own would then
 * have two answers for one gap. A second caller has to say what the gap is.
 */
export function SubjectSearch({
  onPick,
  taken,
  placeholder,
  disabled = false,
}: {
  onPick: (subject: Subject) => void;
  /** Ids already chosen, so the list does not offer them again. */
  taken: Set<number | null>;
  placeholder?: string;
  disabled?: boolean;
}) {
  const { t } = useLingui();
  const [query, setQuery] = useState('');
  const [debounced, setDebounced] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(query.trim()), 300);
    return () => clearTimeout(timer);
  }, [query]);

  const { data } = useQuery({
    queryKey: ['subject-search', debounced],
    queryFn: ({ signal }) => api.searchSubjects(debounced, 6, signal),
    enabled: debounced.length >= 2,
  });

  const results = useMemo(
    () => (data ?? []).filter((subject) => !taken.has(subject.id)),
    [data, taken],
  );

  return (
    <>
      <div className={ui.field}>
        {/* Stacked with the price fields inside a service card, this one has to
            say at a glance that it is not another price. */}
        <SearchIcon size={18} className={ui.fieldIcon} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={placeholder ?? t`Добавить предмет — математика, čeština, физика`}
          disabled={disabled}
          maxLength={200}
          style={{ all: 'unset', flex: 1, minWidth: 0 }}
        />
      </div>
      {/* No wrapper and no margin of its own: the only caller stacks this
          inside a service card, and the card spaces everything in it. */}
      {results.length > 0 ? (
        <Rows>
          {results.map((subject) => (
            <Row
              key={subject.id}
              title={subject.name}
              onClick={() => {
                onPick(subject);
                setQuery('');
                setDebounced('');
              }}
            />
          ))}
        </Rows>
      ) : null}
    </>
  );
}
