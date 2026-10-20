import { Trans } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { NavLink, Outlet } from 'react-router';

import css from './BrowserShell.module.css';
import { browserSessionQuery, consoleChanges } from './queries';

/**
 * The menu and the room for a screen, for the console opened in a browser.
 *
 * The menu lists only what a browser can reach: the catalog and the partners
 * ask the catalog API, which takes a Telegram signature and nothing else, so
 * they stay in the Mini App until that API learns another way in.
 *
 * Whether the viewer is signed in is the screens' business (`ConsoleGate`), as
 * it is in the Mini App; this frame only offers the way out when there is a
 * session to end.
 */
export default function BrowserShell() {
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
      <aside className={css.side}>
        <div className={css.brand}>
          Konnekt
          <small>
            <Trans>консоль</Trans>
          </small>
        </div>
        <nav aria-label="Консоль" style={{ display: 'contents' }}>
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
            <Trans>Люди</Trans>
          </div>
          <Item to="/console/audience">
            <Trans>Аудитория</Trans>
          </Item>
          <div className={css.group}>
            <Trans>Система</Trans>
          </div>
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
        <Outlet />
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
