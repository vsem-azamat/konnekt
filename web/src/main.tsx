import { I18nProvider } from '@lingui/react';
import {
  MutationCache,
  QueryCache,
  QueryClient,
  QueryClientProvider,
} from '@tanstack/react-query';
import {
  backButton,
  init,
  initData,
  isTMA,
  mainButton,
  miniApp,
  on,
  postEvent,
  retrieveLaunchParams,
  swipeBehavior,
  themeParams,
  viewport,
} from '@tma.js/sdk-react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';
import { endsSession, isBrowserConsolePath } from '@/console/browser';
import { BrowserConsoleContext } from '@/console/browserContext';
import { catalogThroughConsole } from '@/console/catalogDoor';
import { isFinal } from '@/console/session';
import { paintChrome } from '@/hooks/useTelegram';
import { activateLocale, i18n, resolveLocale } from '@/i18n';
import { ApiError, api, rawInitData, routeCatalogCalls } from '@/lib/api';
import { followAppHeight } from '@/lib/appHeight';
import {
  createReporter,
  describeError,
  flushClientEvents,
  layoutLooksBroken,
  type Reporter,
  reportClientEvent,
  scrub,
  startReporting,
} from '@/lib/clientErrors';
import { followKeyboard } from '@/lib/keyboard';
import { subscribeTheme } from '@/lib/theme';
import LandingPage from '@/pages/Landing';
import { router } from '@/router';

import './index.css';

/**
 * Startup, in order: fake the Telegram environment if we are not in it, bring
 * up the SDK, pick a language, then render. Each step depends on the one before
 * it, which is why this is a sequence and not a set of effects.
 */
async function bootstrap(): Promise<void> {
  // Before anything else, and in particular before the mock: outside Telegram
  // there is no account, no chat to notify and nothing to sign a request
  // with, so the catalog cannot run. That is a landing page, not an error.
  if (showLanding()) {
    // A browser gets the console where it is meant to open and the landing
    // page everywhere else; which host is which is the server's business.
    if (isBrowserConsolePath(window.location.pathname)) {
      await renderBrowserConsole();
    } else {
      await renderLanding();
    }
    return;
  }

  if (import.meta.env.DEV) {
    // Dynamic import so the mock never reaches the production bundle.
    const { mockEnv } = await import('@/mockEnv');
    mockEnv();
    await enableMobileConsole();
  }

  initSdk();
  reportFailures();
  reportLaunch();
  await initLocale();
  render();
}

/** One line in the console's audience per launch, never in the way of the app. */
function reportLaunch(): void {
  const raw = rawInitData();
  if (raw) void api.reportLaunch(raw).catch(() => undefined);
}

/**
 * Tell the server what fails in this app (lib/clientErrors.ts), from here on.
 *
 * Inside Telegram and in a build only: the console in a browser has no
 * initData to sign a report with, and the development mock's is unsigned, so
 * the server would refuse every one.
 */
function reportFailures(): void {
  if (import.meta.env.DEV) return;
  const initData = rawInitData();
  if (!initData) return;
  const { tgWebAppPlatform, tgWebAppVersion } = retrieveLaunchParams();
  const reporter = createReporter({
    send: (events, leaving) =>
      api.reportClientErrors(
        {
          init_data: initData,
          version: import.meta.env.VITE_APP_VERSION || 'unknown',
          platform: tgWebAppPlatform,
          tg_version: tgWebAppVersion,
          events,
        },
        leaving,
      ),
    route: routePattern,
  });
  startReporting(reporter);

  window.addEventListener('error', (event) => {
    report(reporter, 'error', event.error ?? event.message);
  });
  window.addEventListener('unhandledrejection', (event) => {
    report(reporter, 'unhandled_rejection', event.reason);
  });
  // A batch still waiting when the app is put away or closed goes now: a
  // Mini App is often never seen again after that.
  window.addEventListener('pagehide', reporter.flush);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') reporter.flush();
    else setTimeout(checkLayout, LAYOUT_CHECK_MS);
  });
  // Restored from minimised, Android may say so only through Telegram's own
  // event, and that return is exactly where the height went stale before.
  on('visibility_changed', ({ is_visible }) => {
    if (is_visible) setTimeout(checkLayout, LAYOUT_CHECK_MS);
  });
  setTimeout(checkLayout, LAYOUT_CHECK_MS);
}

function report(
  reporter: Reporter,
  kind: 'error' | 'unhandled_rejection',
  thrown: unknown,
) {
  const { message, stack, ignore } = describeError(thrown);
  if (!ignore) reporter.report({ kind, message, stack });
}

/** The screen as the router names it, `/chats/:group`: never the address itself. */
function routePattern(): string {
  const paths = router.state.matches.map((match) => match.route.path).filter(Boolean);
  return `/${paths.join('/')}`.replace(/\/+/g, '/');
}

/** Long enough for a client that answers the viewport request to have answered. */
const LAYOUT_CHECK_MS = 1500;
let layoutReported = false;

/**
 * Once per session, if the app is a sliver of its window: the bug where a
 * stale viewport height left a heading and nothing under it.
 */
function checkLayout(): void {
  const root = document.getElementById('root');
  if (layoutReported || !root || document.visibilityState !== 'visible') return;
  const height = root.getBoundingClientRect().height;
  if (!layoutLooksBroken(height, window.innerHeight)) return;
  layoutReported = true;
  reportClientEvent({
    kind: 'layout',
    message: `app ${Math.round(height)}px in a ${window.innerHeight}px window`,
  });
}

/**
 * Is this a browser rather than Telegram?
 *
 * In development the answer is always no unless `?landing` says otherwise:
 * the mock has not run yet at this point, so `isTMA()` would say "browser" to
 * every local session and the app would never start.
 *
 * That override is development-only on purpose. In production a browser
 * already lands here on its own, so honouring the parameter could achieve
 * exactly one thing — stranding somebody inside Telegram on a page whose only
 * button sends them to Telegram.
 */
function showLanding(): boolean {
  if (import.meta.env.DEV) {
    // Remembered for the tab, because the router drops the parameter on its
    // first navigation; `?landing=0` forgets it.
    const landing = new URLSearchParams(window.location.search).get('landing');
    if (landing === '0') sessionStorage.removeItem('dev-browser');
    else if (landing !== null) sessionStorage.setItem('dev-browser', '1');
    return sessionStorage.getItem('dev-browser') === '1';
  }
  return !isTMA();
}

async function renderLanding(): Promise<void> {
  // The same precedence the app itself uses, with the browser standing in for
  // Telegram's `language_code`: a stored choice outranks it.
  const locale = resolveLocale(navigator.language);
  await activateLocale(locale);
  document.documentElement.lang = locale;

  const container = document.getElementById('root');
  if (!container) throw new Error('#root is missing from index.html');

  createRoot(container).render(
    <StrictMode>
      <I18nProvider i18n={i18n}>
        <LandingPage />
      </I18nProvider>
    </StrictMode>,
  );
}

/** Set once the console is rendered for a browser; see `queryCache` below. */
let browserMode = false;

async function renderBrowserConsole(): Promise<void> {
  browserMode = true;
  // No initData here: the catalog's screens are asked of webapi (#293).
  routeCatalogCalls(catalogThroughConsole);
  const { browserRouter } = await import('@/console/browserRouter');
  const locale = resolveLocale(navigator.language);
  await activateLocale(locale);
  document.documentElement.lang = locale;

  const container = document.getElementById('root');
  if (!container) throw new Error('#root is missing from index.html');

  createRoot(container).render(
    <StrictMode>
      <I18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <BrowserConsoleContext.Provider value={true}>
            <RouterProvider router={browserRouter} />
          </BrowserConsoleContext.Provider>
        </QueryClientProvider>
      </I18nProvider>
    </StrictMode>,
  );
}

/**
 * Bring up the SDK and mount the features this app uses.
 *
 * Mounting is per-feature and not free, so only what is actually used is
 * mounted. `bindCssVars` publishes Telegram's palette and its insets as CSS
 * variables; the app uses the insets for layout but keeps its own colours, and
 * hands those colours back to Telegram so the chrome around the page matches.
 */
function initSdk(): void {
  init();

  themeParams.mount.ifAvailable();
  themeParams.bindCssVars.ifAvailable();

  // A Mini App opens as a part-height sheet on a phone, and the gesture that
  // grows it is the one disabled below. Ask for the whole screen rather than
  // leaving someone in a half sheet with no way out of it. Before the mount
  // and outside its promise, deliberately: `web_app_expand` needs neither, and
  // a client that never answers the viewport request must not be able to take
  // the swipe away without giving the height back.
  viewport.expand.ifAvailable();

  // Also outside the promise. Subscribing to a signal does not require the
  // mount to have settled, and the subscriber fires when the client answers —
  // so a request that never comes back costs a fallback height rather than a
  // page with no height at all.
  bindAppHeight();
  bindKeyboard();

  // Async: the viewport has to ask the client for its dimensions. Nothing
  // downstream waits on it, so the promise is deliberately not awaited — the
  // signals simply start out at zero and fill in.
  const mounted = viewport.mount.ifAvailable();
  if (mounted.ok) {
    void Promise.resolve(mounted.data)
      .then(() => {
        viewport.bindCssVars.ifAvailable();
      })
      .catch((error: unknown) => {
        console.error('[tma] viewport failed to mount', error);
      });
  }

  // Telegram reads a downward drag as "dismiss this app". On a screen with
  // nothing to scroll that drag and a scroll are the same movement, so the app
  // appeared to scroll where there was nothing to see. Off, then — Telegram's
  // own close button is still there, and it is the unambiguous one.
  // `ifAvailable` because this is Mini Apps 7.7; older clients keep the swipe.
  if (swipeBehavior.mount.ifAvailable().ok) {
    swipeBehavior.disableVertical.ifAvailable();
  }

  // Mounted here, driven from components via the hooks in @/hooks/useTelegram.
  backButton.mount.ifAvailable();
  mainButton.mount.ifAvailable();

  miniApp.mount.ifAvailable();
  // The palette is already on the document — index.html resolves it before the
  // first paint — so Telegram can be told the right colour straight away, and
  // told again whenever it changes. Subscribed here rather than from a screen
  // because the frame around the page belongs to no screen in particular.
  paintChrome();
  subscribeTheme(paintChrome);

  initData.restore();
}

/**
 * Publish the height the app is allowed to occupy, as `--app-height`: the
 * rules are in `lib/appHeight.ts`.
 *
 * Subscribed without waiting for the mount: the signals exist before it, and
 * this way a client that never answers `web_app_request_viewport` leaves the
 * page on its `100dvh` fallback instead of on nothing at all.
 *
 * And asked again whenever the app comes back: active again after being
 * minimised, or visible again after the phone was put away. A height is only
 * as fresh as the client's last report, and a client that restores the sheet
 * without sending one would otherwise leave the app at the height it had while
 * it was away. See docs/invariants.md, «Mini App».
 */
function bindAppHeight(): void {
  followAppHeight(viewport, (height) => {
    document.documentElement.style.setProperty('--app-height', `${height}px`);
  });
  const askAgain = (): void => {
    postEvent('web_app_request_viewport');
  };
  // Telegram's own `activated`: the client's word for this app being the one
  // in front again, which is what restoring a minimised one does.
  on('visibility_changed', ({ is_visible }) => {
    if (is_visible) askAgain();
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') askAgain();
  });
}

/**
 * Publish what the on-screen keyboard covers, as `--keyboard` and
 * `--keyboard-pan`: the rules are in `lib/keyboard.ts`. Inside Telegram only,
 * where the sheets it lifts are.
 *
 * A sheet the keyboard shrinks keeps its scroll, so the field that was in view
 * in the taller sheet can be below the shorter one. It is brought back once
 * the sheet has its new size.
 */
function bindKeyboard(): void {
  if (!window.visualViewport) return;
  const root = document.documentElement.style;
  // The sheet's room is what neither covers. A pan alone moves the sheet
  // without resizing it, and bringing the field back then would pull the
  // sheet's scroll away from wherever the person had taken it.
  let room = 0;
  followKeyboard(
    window.visualViewport,
    () => window.innerHeight,
    ({ covered, panned }) => {
      root.setProperty('--keyboard', `${covered}px`);
      root.setProperty('--keyboard-pan', `${panned}px`);
      if (covered + panned === room) return;
      room = covered + panned;
      requestAnimationFrame(() => {
        const typing = document.activeElement;
        if (typing?.closest('[role="dialog"]')) {
          typing.scrollIntoView({ block: 'nearest' });
        }
      });
    },
  );
}

/** Load the one catalog we need before the first paint, to avoid a flash. */
async function initLocale(): Promise<void> {
  const locale = resolveLocale(initData.user()?.language_code);
  await activateLocale(locale);
  document.documentElement.lang = locale;
}

/**
 * A console on the phone itself.
 *
 * Remote debugging a Mini App on iOS means a cable and a Mac; this is the
 * cheaper 90% of it. Development only.
 */
async function enableMobileConsole(): Promise<void> {
  try {
    const { default: eruda } = await import('eruda');
    eruda.init();
  } catch (error) {
    console.warn('[dev] eruda failed to load', error);
  }
}

function signInAgain(error: unknown): void {
  if (browserMode && endsSession(error)) window.location.assign('/login');
}

const queryClient = new QueryClient({
  // A session that ended while a screen was open, in a read or in a save:
  // webapi answers 401, and a browser has no initData to open another, so the
  // way on is signing in again.
  queryCache: new QueryCache({ onError: signInAgain }),
  mutationCache: new MutationCache({ onError: signInAgain }),
  defaultOptions: {
    queries: {
      // Mobile data. Refetching on every window focus is a poor trade here.
      refetchOnWindowFocus: false,
      staleTime: 30_000,
      retry: (failureCount, error) => {
        // Nothing the client got wrong gets better by asking again: rejected
        // init data stays rejected, and a profile that does not exist will
        // not appear. Retrying only delays the message the user needs, which
        // is why a missing profile used to sit on a skeleton for seconds.
        if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
          return false;
        }
        // The console's webapi half says for itself when asking again is futile.
        if (isFinal(error)) return false;
        return failureCount < 2;
      },
    },
  },
});

/**
 * A render error, with the component stack in place of the script's: in a
 * minified build the components are what still says where it happened.
 */
function renderFailed(error: unknown, info: { componentStack?: string }): void {
  console.error(error);
  const { message, stack, ignore } = describeError(error);
  if (ignore) return;
  reportClientEvent({
    kind: 'render',
    message,
    stack: info.componentStack ? scrub(info.componentStack, 2000) : stack,
  });
}

function render(): void {
  const container = document.getElementById('root');
  if (!container) throw new Error('#root is missing from index.html');

  createRoot(container, {
    // React logs these itself unless told what to do with them; it still should.
    onCaughtError: renderFailed,
    onUncaughtError: renderFailed,
  }).render(
    <StrictMode>
      <I18nProvider i18n={i18n}>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </I18nProvider>
    </StrictMode>,
  );
}

bootstrap().catch((error: unknown) => {
  // Reaching here means the app never rendered, so there is no error boundary
  // to catch it and no UI to report it in. Say something in plain text rather
  // than leaving a white screen.
  console.error('[boot] failed to start', error);
  // Reported when the reporter got that far: nothing else would tell us.
  const { message, stack } = describeError(error);
  reportClientEvent({ kind: 'error', message, stack });
  flushClientEvents();

  const container = document.getElementById('root');
  if (container) {
    const message =
      error instanceof Error && /launch params|unknown env/i.test(error.message)
        ? 'This app has to be opened from Telegram.'
        : 'Something went wrong while starting up. Please reopen the app.';
    container.textContent = message;
  }
});
