import { Trans, useLingui } from '@lingui/react/macro';
import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { useEffect, useId, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router';

import { SearchIcon } from '@/components/icons';

import { consoleSearchQuery } from './queries';
import { type Found, foundList, searchText } from './search';
import { personName } from './session';
import css from './TopSearch.module.css';

// Asked once typing pauses, not on every key.
const PAUSE = 250;

/**
 * The top bar's search across chats and people (#288, layout A): a field, and
 * under it a few of each as links. The arrows walk from the field through
 * them, Enter opens one, Escape goes back to the field.
 */
export default function TopSearch() {
  const { t } = useLingui();
  const { pathname } = useLocation();
  const box = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState('');
  const [asked, setAsked] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  // Enter pressed before the answer to what is typed came: open its first.
  const [wantFirst, setWantFirst] = useState(false);
  // Focus handed back to the field by Escape, which must not reopen the list.
  const quiet = useRef(false);
  const panelId = useId();

  useEffect(() => {
    const id = setTimeout(() => setAsked(searchText(typed)), PAUSE);
    return () => clearTimeout(id);
  }, [typed]);

  // A new screen closes the list; what was typed stays, to search again.
  // biome-ignore lint/correctness/useExhaustiveDependencies: it re-runs on navigation
  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return;
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [open]);

  const results = useQuery({
    ...consoleSearchQuery(asked ?? ''),
    enabled: asked !== null,
    placeholderData: keepPreviousData,
  });
  const list = asked !== null && results.data ? foundList(results.data) : [];
  const showing = open && searchText(typed) !== null;
  // Still the answer to something typed before: shown, but not opened by Enter.
  const stale = asked !== searchText(typed) || results.isPlaceholderData;

  const openFirst = () => box.current?.querySelector<HTMLElement>('a[href]')?.click();
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs when the answer to what is typed arrives
  useEffect(() => {
    if (!wantFirst || stale || results.isFetching) return;
    setWantFirst(false);
    openFirst();
  }, [wantFirst, stale, results.isFetching]);
  const chats = list.filter((found) => found.kind === 'chat');
  const people = list.filter((found) => found.kind === 'person');

  // The field and the links, in the order the arrows walk them.
  const stops = () => [
    ...(field.current ? [field.current] : []),
    ...(box.current?.querySelectorAll<HTMLElement>('a[href]') ?? []),
  ];
  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === 'Escape') {
      // Not the browser's own clearing of a search field: the first Escape
      // closes the list, the second clears the text.
      event.preventDefault();
      if (showing) setOpen(false);
      else setTyped('');
      quiet.current = true;
      field.current?.focus();
      quiet.current = false;
      return;
    }
    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
    event.preventDefault();
    setOpen(true);
    const all = stops();
    const at = all.indexOf(document.activeElement as HTMLElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    all[(at + step + all.length) % all.length]?.focus();
  };

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: the keys bubble here from the field and the links in it
    <div
      ref={box}
      className={css.box}
      onKeyDown={onKey}
      onBlur={(event) => {
        // Only when the focus went somewhere: a click inside on what takes
        // none blurs with nowhere, and an outside click is the pointer's.
        const to = event.relatedTarget as Node | null;
        if (to && !box.current?.contains(to)) setOpen(false);
      }}
    >
      <label className={css.field}>
        <SearchIcon size={16} />
        <input
          ref={field}
          type="search"
          aria-controls={panelId}
          aria-label={t`Поиск по чатам и людям`}
          placeholder={t`Чат, человек, @username или id`}
          value={typed}
          maxLength={64}
          onChange={(event) => {
            setTyped(event.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            if (!quiet.current) setOpen(true);
          }}
          onKeyDown={(event) => {
            // Enter opens the first thing found, as a click on it would; for
            // what was just typed, once its answer comes.
            if (event.key !== 'Enter') return;
            if (!stale) return void openFirst();
            setAsked(searchText(typed));
            setWantFirst(true);
          }}
        />
      </label>
      {showing ? (
        // The focus stays in the field through a click in the list: the
        // screen behind would take it, blur the field and close the list
        // before the click lands (Safari never focuses a clicked link).
        // biome-ignore lint/a11y/noStaticElementInteractions: it only keeps the focus where it was
        <div
          id={panelId}
          className={css.panel}
          onMouseDown={(event) => event.preventDefault()}
        >
          {chats.length > 0 ? (
            <Group title={t`Чаты`} found={chats} onOpen={() => setOpen(false)} />
          ) : null}
          {people.length > 0 ? (
            <Group title={t`Люди`} found={people} onOpen={() => setOpen(false)} />
          ) : null}
          <p className={css.note} aria-live="polite">
            {asked === null || results.isPending || stale ? (
              <Trans>Ищем…</Trans>
            ) : results.isError ? (
              <Trans>Не удалось найти. Попробуйте ещё раз.</Trans>
            ) : list.length === 0 ? (
              <Trans>Ничего не нашлось.</Trans>
            ) : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}

function Group({
  title,
  found,
  onOpen,
}: {
  title: string;
  found: Found[];
  onOpen: () => void;
}) {
  const id = useId();
  // A label, not a heading: the top bar's list is no part of the page's outline.
  return (
    <>
      <p id={id} className={css.group}>
        {title}
      </p>
      <ul aria-labelledby={id}>
        {found.map((one) => (
          <li key={one.kind === 'chat' ? `c${one.chat.id}` : `p${one.person.user_id}`}>
            <Entry found={one} onOpen={onOpen} />
          </li>
        ))}
      </ul>
    </>
  );
}

function Entry({ found, onOpen }: { found: Found; onOpen: () => void }) {
  const { t } = useLingui();
  const status: Record<string, string> = {
    approved: t`модерирует`,
    discovered: t`ждёт решения`,
    observed: t`наблюдает`,
    external: t`только ссылка`,
    disabled: t`отключён`,
  };
  let name: string;
  let line: (string | null)[];
  if (found.kind === 'chat') {
    name = found.chat.title ?? String(found.chat.id);
    line = [status[found.chat.resource_status] ?? null, String(found.chat.id)];
  } else {
    const { person } = found;
    name = personName(person);
    line = [
      person.username && name !== `@${person.username}` ? `@${person.username}` : null,
      String(person.user_id),
      person.blocked ? t`в чёрном списке` : null,
      found.to ? null : t`нет карточки`,
    ];
  }
  const body = (
    <>
      <span className={css.name}>{name}</span>
      <small>{line.filter(Boolean).join(' · ')}</small>
    </>
  );
  return found.to ? (
    // Closed here too: the screen already open does not change the path.
    <Link to={found.to} className={css.entry} onClick={onOpen}>
      {body}
    </Link>
  ) : (
    <div className={[css.entry, css.inert].join(' ')}>{body}</div>
  );
}
