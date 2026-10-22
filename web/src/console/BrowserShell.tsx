import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigationType } from 'react-router';
import {
  BellIcon,
  BlockIcon,
  BookIcon,
  CardIcon,
  ChatIcon,
  GearIcon,
  HomeIcon,
  PeopleIcon,
  ShieldIcon,
} from '@/components/icons';
import { ApiError } from '@/lib/api';

import css from './BrowserShell.module.css';
import {
  adminCatalogQuery,
  browserSessionQuery,
  consoleChanges,
  consoleSignalsQuery,
} from './queries';
import { isFinal } from './session';
import { menuCounts } from './signals';
import TopSearch from './TopSearch';

/**
 * The menu and the room for a screen, for the console opened in a browser.
 *
 * The menu lists the console's screens, the catalog's among them: webapi asks
 * the catalog for the signed-in super admin (#293). Beside a screen, how many
 * wait there for an admin, read again every minute while the console is open.
 *
 * Whether the viewer is signed in is the screens' business (`ConsoleGate`), as
 * it is in the Mini App; this frame only offers the way out when there is a
 * session to end.
 */
export default function BrowserShell() {
  const { t } = useLingui();
  const { pathname } = useLocation();
  const navigation = useNavigationType();
  const menu = useRef<HTMLElement>(null);
  const screen = useRef<HTMLElement>(null);
  const bar = useRef<HTMLElement>(null);
  // On a narrow window the menu is a row that scrolls sideways: bring the
  // current screen's link into view rather than leave it off the edge.
  // The screen is the one scroller, and it stays mounted across screens: a
  // new one opens at its top (Back keeps where it was), and takes the focus
  // from the menu link, so the keys scroll it and a reader lands on it.
  // biome-ignore lint/correctness/useExhaustiveDependencies: it re-runs on navigation; the current link is read from the DOM
  useEffect(() => {
    menu.current
      ?.querySelector('[aria-current="page"]')
      ?.scrollIntoView({ inline: 'center', block: 'nearest' });
    if (!screen.current) return;
    if (navigation !== 'POP') screen.current.scrollTop = 0;
    const from = document.activeElement;
    if (from && (menu.current?.contains(from) || bar.current?.contains(from))) {
      screen.current.focus({ preventScroll: true });
    }
  }, [pathname]);
  const queryClient = useQueryClient();
  const session = useQuery(browserSessionQuery);
  // Not again after a refusal that another try cannot change (webapi's say
  // so for themselves, the catalog's are its 4xx); an outage or a deploy is
  // asked again, or the badges would freeze at their last number.
  const every = ({ state: { error } }: { state: { error: unknown } }) =>
    isFinal(error) ||
    (error instanceof ApiError && error.status >= 400 && error.status < 500)
      ? false
      : 60_000;
  const signals = useQuery({ ...consoleSignalsQuery, refetchInterval: every });
  const catalog = useQuery({ ...adminCatalogQuery, refetchInterval: every });
  const counts = menuCounts(signals.data, catalog.data?.counts);
  const signOut = useMutation({
    mutationFn: consoleChanges.signOut,
    onSettled: () => {
      queryClient.clear();
      window.location.assign('/login');
    },
  });

  return (
    <div className={css.frame}>
      <aside ref={menu} className={css.side}>
        <div className={css.brand}>
          Konnekt
          <small>
            <Trans>админка</Trans>
          </small>
        </div>
        <nav aria-label={t`Консоль`} style={{ display: 'contents' }}>
          <Item to="/console" end icon={<HomeIcon size={17} />}>
            <Trans>Обзор</Trans>
          </Item>
          <Item
            to="/console/signals"
            icon={<BellIcon size={17} />}
            count={counts.signals}
          >
            <Trans>Сигналы</Trans>
          </Item>
          <div className={css.group}>
            <Trans>Модерация</Trans>
          </div>
          <Item to="/console/chats" icon={<ChatIcon size={17} />} count={counts.chats}>
            <Trans>Чаты</Trans>
          </Item>
          <Item to="/console/spam" icon={<ShieldIcon size={17} />} count={counts.spam}>
            <Trans>Реклама</Trans>
          </Item>
          <Item to="/console/blacklist" icon={<BlockIcon size={17} />}>
            <Trans>Чёрный список</Trans>
          </Item>
          <div className={css.group}>
            <Trans>Каталог</Trans>
          </div>
          <Item
            to="/console/catalog"
            icon={<BookIcon size={17} />}
            count={counts.catalog}
          >
            <Trans>Каталог</Trans>
          </Item>
          <Item to="/console/partners" icon={<CardIcon size={17} />}>
            <Trans>Партнёры</Trans>
          </Item>
          <div className={css.group}>
            <Trans>Люди</Trans>
          </div>
          <Item to="/console/audience" icon={<PeopleIcon size={17} />}>
            <Trans>Аудитория</Trans>
          </Item>
          <Item to="/console/system" icon={<GearIcon size={17} />}>
            <Trans>Система</Trans>
          </Item>
        </nav>
        {session.data ? (
          <div className={css.foot}>
            <span>
              <Trans>Суперадмин</Trans> · {session.data.user_id}
            </span>
            <button
              type="button"
              className={css.out}
              disabled={signOut.isPending}
              onClick={() => signOut.mutate()}
            >
              <Trans>Выйти</Trans>
            </button>
          </div>
        ) : null}
      </aside>
      <main ref={screen} tabIndex={-1} className={css.main}>
        <header ref={bar} className={css.top}>
          <TopSearch />
          <Link
            to="/console/signals"
            className={css.bell}
            aria-label={
              counts.signals > 0
                ? t`Сигналы, ждут решения: ${counts.signals}`
                : t`Сигналы`
            }
            title={t`Сигналы`}
          >
            <BellIcon size={17} />
            {counts.signals > 0 ? (
              <span className={css.badge}>{counts.signals}</span>
            ) : null}
          </Link>
        </header>
        <div className={css.content}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Item({
  to,
  end,
  icon,
  count = 0,
  children,
}: {
  to: string;
  end?: boolean;
  icon: React.ReactNode;
  /** How many wait there; none shows no badge. */
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <NavLink to={to} end={end} className={css.link}>
      {icon}
      <span>{children}</span>
      {count > 0 ? <span className={css.badge}>{count}</span> : null}
    </NavLink>
  );
}
