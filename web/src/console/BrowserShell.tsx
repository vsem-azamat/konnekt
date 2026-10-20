import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router';

import css from './BrowserShell.module.css';
import { browserSessionQuery, consoleChanges } from './queries';

/**
 * The menu and the room for a screen, for the console opened in a browser.
 *
 * The menu lists the console's screens, the catalog's among them: webapi asks
 * the catalog for the signed-in super admin (#293).
 *
 * Whether the viewer is signed in is the screens' business (`ConsoleGate`), as
 * it is in the Mini App; this frame only offers the way out when there is a
 * session to end.
 */
export default function BrowserShell() {
  const { t } = useLingui();
  const { pathname } = useLocation();
  const menu = useRef<HTMLElement>(null);
  // On a narrow window the menu is a row that scrolls sideways: bring the
  // current screen's link into view rather than leave it off the edge.
  // biome-ignore lint/correctness/useExhaustiveDependencies: it re-runs on navigation; the current link is read from the DOM
  useEffect(() => {
    menu.current
      ?.querySelector('[aria-current="page"]')
      ?.scrollIntoView({ inline: 'center', block: 'nearest' });
  }, [pathname]);
  const queryClient = useQueryClient();
  const session = useQuery(browserSessionQuery);
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
            <Trans>консоль</Trans>
          </small>
        </div>
        <nav aria-label={t`Консоль`} style={{ display: 'contents' }}>
          <Item to="/console" end>
            <Trans>Обзор</Trans>
          </Item>
          <div className={css.group}>
            <Trans>Модерация</Trans>
          </div>
          <Item to="/console/chats">
            <Trans>Чаты</Trans>
          </Item>
          <Item to="/console/spam">
            <Trans>Реклама</Trans>
          </Item>
          <Item to="/console/blacklist">
            <Trans>Чёрный список</Trans>
          </Item>
          <div className={css.group}>
            <Trans>Каталог</Trans>
          </div>
          <Item to="/console/catalog">
            <Trans>Каталог</Trans>
          </Item>
          <Item to="/console/partners">
            <Trans>Партнёры</Trans>
          </Item>
          <div className={css.group}>
            <Trans>Люди</Trans>
          </div>
          <Item to="/console/audience">
            <Trans>Аудитория</Trans>
          </Item>
          <Item to="/console/system">
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
      <main className={css.main}>
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
  children,
}: {
  to: string;
  end?: boolean;
  children: React.ReactNode;
}) {
  return (
    <NavLink to={to} end={end} className={css.link}>
      {children}
    </NavLink>
  );
}
