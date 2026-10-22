import { useLayoutEffect, useRef } from 'react';
import { Outlet, useLocation, useNavigationType } from 'react-router';

import { TabBar } from './TabBar';
import css from './ui.module.css';

/** Where each history entry was left, so Back returns to it. */
const positions = new Map<string, number>();

/**
 * The screens with tabs: the screen above, the bar below it, in the visible
 * area.
 *
 * The bar is a row of this box rather than fixed to the window. Fixed, it was
 * placed against the webview while the screen was sized to Telegram's height,
 * and wherever the two differ one of them was wrong (#345). Here both are
 * measured from the same box, and only the screen scrolls.
 *
 * One scroller serves every tab, so its position is the layout's to keep: a
 * new screen starts at its top, and Back returns to where the previous one was
 * left. A chat's preview is an entry on the same screen, and opening it must
 * not move the list behind it.
 */
export function TabsLayout() {
  const content = useRef<HTMLElement>(null);
  const { key, pathname } = useLocation();
  const action = useNavigationType();
  const shown = useRef(pathname);

  useLayoutEffect(() => {
    const el = content.current;
    if (!el) return;
    if (action === 'POP') el.scrollTop = positions.get(key) ?? 0;
    else if (pathname !== shown.current) el.scrollTop = 0;
    shown.current = pathname;
    positions.set(key, el.scrollTop);
  }, [key, pathname, action]);

  return (
    <div className={css.tabbed}>
      <main
        ref={content}
        className={css.content}
        onScroll={(event) => positions.set(key, event.currentTarget.scrollTop)}
      >
        <Outlet />
      </main>
      <TabBar />
    </div>
  );
}
