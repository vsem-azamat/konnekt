import { useEffect, useLayoutEffect, useRef } from 'react';
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
  // A position Back could not reach yet: the screen came back as a skeleton
  // because its data had left the cache, and the browser caps the scroll at
  // what is there. Held until the screen is tall enough or the person scrolls.
  const owed = useRef<number | null>(null);

  useLayoutEffect(() => {
    const el = content.current;
    if (!el) return;
    owed.current = null;
    if (action === 'POP') {
      const target = positions.get(key) ?? 0;
      el.scrollTop = target;
      if (el.scrollTop < target - 1) owed.current = target;
    } else if (pathname !== shown.current) {
      el.scrollTop = 0;
    }
    shown.current = pathname;
    if (owed.current === null) positions.set(key, el.scrollTop);
  }, [key, pathname, action]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: each entry renders its own screen to watch.
  useEffect(() => {
    const el = content.current;
    const screen = el?.firstElementChild;
    if (!el || !screen) return;
    const grown = new ResizeObserver(() => {
      if (owed.current === null) return;
      el.scrollTop = owed.current;
      if (el.scrollTop >= owed.current - 1) owed.current = null;
    });
    grown.observe(screen);
    return () => grown.disconnect();
  }, [key]);

  const letGo = () => {
    owed.current = null;
  };

  return (
    <div className={css.tabbed}>
      <main
        ref={content}
        className={css.content}
        onScroll={(event) => {
          if (owed.current === null) positions.set(key, event.currentTarget.scrollTop);
        }}
        onTouchStart={letGo}
        onWheel={letGo}
      >
        <Outlet />
      </main>
      <TabBar />
    </div>
  );
}
