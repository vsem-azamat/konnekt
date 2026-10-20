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
  swipeBehavior,
  themeParams,
  viewport,
} from '@tma.js/sdk-react';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { RouterProvider } from 'react-router';
import { endsSession, isBrowserConsolePath } from '@/console/browser';
import { BrowserConsoleContext } from '@/console/browserContext';
import { isFinal } from '@/console/session';
import { paintChrome } from '@/hooks/useTelegram';
import { activateLocale, i18n, resolveLocale } from '@/i18n';
import { ApiError, api, rawInitData } from '@/lib/api';
import { subscribeTheme } from '@/lib/theme';
import LandingPage from '@/pages/Landing';
import { browserRouter, router } from '@/router';

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
 * Publish the height the app is allowed to occupy, as `--app-height`.
 *
 * Telegram's number rather than the webview's. On iOS and Android the SDK does
 * not trust `window.innerHeight` either — it asks the client and waits for
 * `viewport_changed` — so `100dvh`, which is that same untrusted number, can
 * be taller than what the person can actually see. An app sized to the webview
 * then puts its last rows below the visible edge with nothing able to scroll
 * to them, and `index.css` has deliberately left the document unable to.
 *
 * `stableHeight` and not `height`: the plain one follows the drag gesture and
 * would make everything pinned to the bottom jitter.
 *
 * Subscribed rather than read once, and subscribed without waiting for the
 * mount: the signal exists before it, and this way a client that never answers
 * `web_app_request_viewport` leaves the page on its `100dvh` fallback instead
 * of on nothing at all.
 *
 * Zero is not an answer, and skipping it is the whole reason this is not left
 * to `bindCssVars`. The signal reads 0 until the client has reported a stable
 * state, and a variable set to `0px` is *defined* — `var(--app-height, 100dvh)`
 * would resolve to zero rather than fall back, and the app would be one frame
 * of nothing.
 */
function bindAppHeight(): void {
  const publish = (height: number): void => {
    if (height > 0) {
      document.documentElement.style.setProperty('--app-height', `${height}px`);
    }
  };
  publish(viewport.stableHeight());
  viewport.stableHeight.sub(publish);
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

function render(): void {
  const container = document.getElementById('root');
  if (!container) throw new Error('#root is missing from index.html');

  createRoot(container).render(
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

  const container = document.getElementById('root');
  if (container) {
    const message =
      error instanceof Error && /launch params|unknown env/i.test(error.message)
        ? 'This app has to be opened from Telegram.'
        : 'Something went wrong while starting up. Please reopen the app.';
    container.textContent = message;
  }
});
