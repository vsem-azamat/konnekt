import {
  backButton,
  hapticFeedback,
  type MainButtonState,
  mainButton,
  miniApp,
  useSignal,
  viewport,
} from '@tma.js/sdk-react';
import { useEffect, useRef } from 'react';
import { useLocation, useNavigate } from 'react-router';

/**
 * Wrappers over the SDK singletons.
 *
 * Every call goes through `ifAvailable`, which is not defensiveness for its own
 * sake: these features are versioned per Telegram client, and an old Android
 * build that has never heard of `web_app_setup_main_button` should render a
 * page without a main button, not a white screen.
 */

// ── theme ───────────────────────────────────────────────────────────────

/**
 * Tell Telegram what colour the page is.
 *
 * The app does not follow the client's theme — it has its own, see
 * `lib/theme.ts` — so the header and the bottom bar have to be told, or a
 * light page ends up framed in black. The value is read back out of the
 * stylesheet rather than repeated here, so the palette still has exactly one
 * definition. Call this after anything that changes `data-theme`.
 *
 * There is deliberately no hook exposing Telegram's own `themeParams`: a
 * component reaching for it would be following the client's colours, which is
 * the thing this app decided not to do.
 */
export function paintChrome(): void {
  const styles = getComputedStyle(document.documentElement);
  const background = styles.getPropertyValue('--bg').trim();
  if (!background.startsWith('#')) return;

  miniApp.setHeaderColor.ifAvailable(background as `#${string}`);
  miniApp.setBgColor.ifAvailable(background as `#${string}`);
  miniApp.setBottomBarColor.ifAvailable(background as `#${string}`);
}

// ── safe area ───────────────────────────────────────────────────────────

export interface SafeArea {
  top: number;
  bottom: number;
  left: number;
  right: number;
}

export interface SafeAreaInfo {
  /** Insets imposed by the device — the notch and the home indicator. */
  device: SafeArea;
  /** Insets imposed by Telegram's own chrome on top of the device ones. */
  content: SafeArea;
  /** The two summed, which is what layout almost always wants. */
  total: SafeArea;
}

/**
 * Safe area insets in pixels.
 *
 * The same numbers are also published as CSS variables by `bindCssVars` in
 * `main.tsx`; prefer those for layout and reach for this hook only when a
 * measurement has to reach JavaScript.
 */
export function useSafeArea(): SafeAreaInfo {
  const device = useSignal(viewport.safeAreaInsets);
  const content = useSignal(viewport.contentSafeAreaInsets);

  return {
    device,
    content,
    total: {
      top: device.top + content.top,
      bottom: device.bottom + content.bottom,
      left: device.left + content.left,
      right: device.right + content.right,
    },
  };
}

/** Current viewport size and whether it is mid-gesture. */
export function useViewport() {
  return {
    width: useSignal(viewport.width),
    height: useSignal(viewport.height),
    stableHeight: useSignal(viewport.stableHeight),
    isExpanded: useSignal(viewport.isExpanded),
    isFullscreen: useSignal(viewport.isFullscreen),
  };
}

// ── back button ─────────────────────────────────────────────────────────

/**
 * Bind Telegram's back button to the router.
 *
 * Shown only when there is somewhere to go back to. On the first screen the
 * button must stay hidden, otherwise tapping it navigates out of history and
 * the Mini App appears to freeze.
 *
 * Mount this once, in the shell above the routes.
 */
export function useBackButton(): void {
  const navigate = useNavigate();
  const location = useLocation();

  // react-router does not expose the history length, but it does count its own
  // entries in the location key stack.
  const canGoBack = location.key !== 'default';

  useEffect(() => {
    if (canGoBack) {
      backButton.show.ifAvailable();
    } else {
      backButton.hide.ifAvailable();
    }
  }, [canGoBack]);

  useEffect(() => {
    const result = backButton.onClick.ifAvailable(() => {
      void navigate(-1);
    });
    return result.ok ? result.data : undefined;
  }, [navigate]);

  // Leaving the button visible after the shell unmounts would strand it on
  // whatever renders next.
  useEffect(() => () => void backButton.hide.ifAvailable(), []);
}

// ── main button ─────────────────────────────────────────────────────────

export interface MainButtonConfig extends Partial<MainButtonState> {
  /** Called on tap. Omit to leave the button inert. */
  onClick?: VoidFunction;
}

/**
 * Drive the main button from a screen.
 *
 * The button is a singleton owned by Telegram, so this hook takes it over while
 * the calling component is mounted and hides it again on unmount. Two screens
 * using it at once will fight; only the deepest one should.
 *
 * @example
 * useMainButton({ text: t`Send`, isEnabled: canSend, onClick: submit });
 */
export function useMainButton(config: MainButtonConfig | null): void {
  const { onClick, ...state } = config ?? {};
  const isHidden = config === null;

  // Keep the latest handler without re-binding the listener on every render.
  const handler = useRef(onClick);
  handler.current = onClick;

  // Read through a ref so the effect can depend on the serialized value rather
  // than on an object literal that is new on every render.
  const latest = useRef(state);
  latest.current = state;

  const stateKey = JSON.stringify(state);

  /*
   * stateKey is deliberately a dependency that the body never reads: it is the
   * value-equal trigger standing in for `state`, which is a new object on every
   * render and would otherwise re-fire this effect constantly.
   */
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    if (isHidden) {
      mainButton.hide.ifAvailable();
      return;
    }
    mainButton.setParams.ifAvailable({ isVisible: true, ...latest.current });
  }, [stateKey, isHidden]);

  useEffect(() => {
    const result = mainButton.onClick.ifAvailable(() => handler.current?.());
    return result.ok ? result.data : undefined;
  }, []);

  useEffect(() => () => void mainButton.hide.ifAvailable(), []);
}

// ── haptics ─────────────────────────────────────────────────────────────

/**
 * A tick when the selection changes.
 *
 * Telegram's own guidance is explicit that this is for the selection
 * *changing*, not for confirming one — so it belongs on tab switches and
 * filter toggles, and not on the button that sends a message.
 */
export function hapticSelection(): void {
  hapticFeedback.selectionChanged.ifAvailable();
}

/** A short bump for a completed action. */
export function hapticSuccess(): void {
  hapticFeedback.notificationOccurred.ifAvailable('success');
}
