/**
 * The bar at the top of every screen.
 *
 * Two controls, and each earns its place by being something people look for
 * and cannot find: the language and the palette. They belong on every screen
 * rather than inside a settings page, because the answer to "how do I make
 * this light" should not be "leave what you are doing and go somewhere else".
 *
 * It is rendered per screen rather than once above the router. A shared shell
 * would have to know which screens want tabs and which want a back arrow, and
 * that knowledge belongs to the screen.
 */

import { useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { useAppTheme } from '@/hooks/useAppTheme';
import { hapticSelection } from '@/hooks/useTelegram';
import {
  activateLocale,
  LOCALE_NAMES,
  LOCALES,
  type Locale,
  writeLocaleOverride,
} from '@/i18n';
import { api, meQuery } from '@/lib/api';

import { GlobeIcon, MoonIcon, SunIcon } from './icons';
import { Pick, Sheet } from './Sheet';
import css from './ui.module.css';

/** How long a press has to be held to mean "follow the system" rather than "toggle". */
const HOLD_MS = 450;

export function AppHeader() {
  const { t, i18n } = useLingui();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const queryClient = useQueryClient();
  const theme = useAppTheme();
  const me = useQuery(meQuery);
  const onConsole = pathname === '/console';

  const [languageOpen, setLanguageOpen] = useState(false);

  const update = useMutation({
    mutationFn: api.updateMe,
    onSuccess: (next) => {
      queryClient.setQueryData(['me'], next);
      // Subject and faculty names come back translated, so a language change
      // invalidates everything the server rendered.
      void queryClient.invalidateQueries();
    },
  });

  const chooseLocale = async (locale: Locale) => {
    hapticSelection();
    setLanguageOpen(false);
    await activateLocale(locale);
    document.documentElement.lang = locale;
    // Remembered locally as well as on the server: the next launch reads it
    // before the first request has come back.
    writeLocaleOverride(locale);
    update.mutate({ ui_lang: locale });
  };

  // Tap swaps light and dark; holding returns to "follow the system". Three
  // states, one button — and the state nobody thinks about is the one that
  // takes the deliberate gesture.
  const holdTimer = useRef<number | null>(null);
  const held = useRef(false);

  const startHold = () => {
    held.current = false;
    holdTimer.current = window.setTimeout(() => {
      holdTimer.current = null;
      held.current = true;
      hapticSelection();
      theme.set('system');
    }, HOLD_MS);
  };

  const endHold = () => {
    if (holdTimer.current === null) return;
    window.clearTimeout(holdTimer.current);
    holdTimer.current = null;
  };

  const toggleTheme = () => {
    // The hold already changed it, and a click still follows the pointer
    // release. Without this the toggle would immediately undo the hold.
    if (held.current) {
      held.current = false;
      return;
    }
    hapticSelection();
    theme.set(theme.theme === 'dark' ? 'light' : 'dark');
  };

  const locale = LOCALES.find((code) => code === i18n.locale) ?? 'ru';

  return (
    <header className={css.head}>
      <span className={css.wordmark}>Konnekt</span>

      <div className={css.headActions}>
        <button
          type="button"
          className={`${css.iconBtn} ${css.langBtn}`}
          aria-label={t`Язык приложения`}
          aria-haspopup="dialog"
          onClick={() => {
            hapticSelection();
            setLanguageOpen(true);
          }}
        >
          <GlobeIcon size={13} />
          {locale.toUpperCase()}
        </button>

        <button
          type="button"
          className={css.iconBtn}
          aria-label={
            theme.choice === 'system'
              ? t`Оформление: как в системе. Нажми, чтобы сменить`
              : t`Оформление. Нажми, чтобы сменить; удерживай, чтобы вернуть системное`
          }
          onClick={toggleTheme}
          onPointerDown={startHold}
          onPointerUp={endHold}
          onPointerLeave={endHold}
          onPointerCancel={endHold}
        >
          {theme.theme === 'dark' ? <MoonIcon size={15} /> : <SunIcon size={15} />}
        </button>

        {me.data?.is_admin ? (
          <button
            type="button"
            className={`${css.iconBtn} ${css.consoleBtn}`}
            aria-current={onConsole ? 'page' : undefined}
            onClick={() => {
              if (onConsole) return;
              hapticSelection();
              navigate('/console');
            }}
          >
            {t`Консоль`}
          </button>
        ) : null}
      </div>

      {languageOpen ? (
        <Sheet
          title={t`Язык`}
          closeLabel={t`Закрыть`}
          onClose={() => setLanguageOpen(false)}
        >
          {LOCALES.map((code) => (
            <Pick
              key={code}
              name={LOCALE_NAMES[code]}
              selected={code === locale}
              onClick={() => void chooseLocale(code)}
            />
          ))}
        </Sheet>
      ) : null}
    </header>
  );
}
