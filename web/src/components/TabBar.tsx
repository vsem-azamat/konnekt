import { Trans, useLingui } from '@lingui/react/macro';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { hapticSelection } from '@/hooks/useTelegram';

import { BookmarkIcon, ChatIcon, PersonIcon, PlusIcon, SearchIcon } from './icons';
import { Pick, Sheet } from './Sheet';
import { Tile } from './Ui';
import css from './ui.module.css';

/**
 * Four destinations and one action.
 *
 * "Чаты" is the directory of moderated student chats (supervisor-telegram's),
 * a real list behind the tab. "Помощь" is the catalog. "Профиль" holds a
 * student's and a helper's own things, which the marketplace made too many to
 * hide behind an avatar in the header.
 *
 * The round button is not a fifth tab: it posts something, which is the
 * opposite direction from browsing, and keeping it visually apart is what says
 * so.
 */
const TABS = [
  { to: '/', icon: SearchIcon, label: <Trans>Помощь</Trans> },
  { to: '/chats', icon: ChatIcon, label: <Trans>Чаты</Trans> },
  { to: '/mine', icon: BookmarkIcon, label: <Trans>Заявки</Trans> },
  { to: '/profile', icon: PersonIcon, label: <Trans>Профиль</Trans> },
] as const;

/** A tab stays lit on the screens below it: a chat section is still Чаты. */
function isOn(to: string, pathname: string): boolean {
  return to === '/' ? pathname === '/' : pathname === to || pathname.startsWith(`${to}/`);
}

export function TabBar() {
  const { t } = useLingui();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [posting, setPosting] = useState(false);

  const go = (to: string) => {
    if (to !== pathname) hapticSelection();
    navigate(to);
  };

  const post = (to: string) => {
    hapticSelection();
    setPosting(false);
    navigate(to);
  };

  return (
    <nav className={css.tabs}>
      {TABS.map(({ to, icon: Icon, label }) => (
        <button
          key={to}
          type="button"
          className={css.tab}
          aria-current={isOn(to, pathname) ? 'page' : undefined}
          onClick={() => go(to)}
        >
          <Icon size={21} />
          {label}
        </button>
      ))}

      <button
        type="button"
        className={css.fab}
        aria-label={t`Разместить`}
        aria-haspopup="dialog"
        onClick={() => {
          hapticSelection();
          setPosting(true);
        }}
      >
        <PlusIcon size={20} />
      </button>

      {/*
        Asked here rather than settled by a mode switch at the top of the app.
        A student/helper toggle doubles the interface for the few people who
        offer something, and makes everyone else carry a control they will
        never touch. The question costs one tap, and only the people who press
        the button ever see it.
      */}
      {posting ? (
        <Sheet
          title={t`Что делаем?`}
          closeLabel={t`Закрыть`}
          onClose={() => setPosting(false)}
        >
          <Pick
            leading={
              <Tile tone={0}>
                <SearchIcon size={19} />
              </Tile>
            }
            name={<Trans>Мне нужна помощь</Trans>}
            hint={<Trans>опиши задачу — придут отклики</Trans>}
            onClick={() => post('/ask')}
          />
          <Pick
            leading={
              <Tile tone={1}>
                <PlusIcon size={19} />
              </Tile>
            }
            name={<Trans>Предлагаю услугу</Trans>}
            hint={<Trans>репетиторство, работы, помощь</Trans>}
            onClick={() => post('/offer')}
          />
        </Sheet>
      ) : null}
    </nav>
  );
}
