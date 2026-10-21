/**
 * The app telling us what failed in it, so nobody has to.
 *
 * Uncaught errors, unhandled rejections, render errors, failed API calls, an
 * empty screen where data was expected and an app far shorter than its window
 * go to `POST /api/public/client-errors`, which logs and counts them
 * (app/webapi/routes/client_errors.py). Each event names the screen by its
 * route pattern and a call by its endpoint pattern, never by the address: an
 * address can carry a group's name, an id, and in its fragment initData.
 * Nothing about the person goes in an event; the initData that signs the
 * report is checked there and never written.
 *
 * Batched, deduplicated and capped per session, so a failure in a loop costs
 * one event and a broken screen cannot flood the log.
 */

export type ClientEventKind =
  | 'error'
  | 'unhandled_rejection'
  | 'render'
  | 'api'
  | 'empty'
  | 'layout';

export interface ClientEvent {
  kind: ClientEventKind;
  message?: string;
  stack?: string;
  route: string;
  endpoint?: string;
  status?: number;
}

/** A request to the endpoint: the events, the build and the client they came from. */
export interface ClientErrorReport {
  init_data: string;
  version: string;
  platform: string;
  tg_version: string;
  events: ClientEvent[];
}

/** How long events wait for company before they go. */
export const FLUSH_MS = 3000;
/** Events per session; past that the app has said enough. */
export const PER_SESSION = 30;
/** Events per request, below the server's own cap. */
const PER_BATCH = 10;
// The server's limits; a longer field is cut here rather than refused there.
const MESSAGE_CHARS = 500;
const STACK_CHARS = 2000;

/**
 * The query and fragment of an address whatever its scheme, initData on its
 * own, and numbers long enough to name somebody. The server scrubs the same.
 */
const ADDRESS_TAIL = /([a-z][a-z0-9+.-]*:\/\/[^\s?#]*)[?#]\S*/gi;
const INIT_DATA = /tgWebAppData=\S*/gi;
const LONG_NUMBER = /\d{6,}/g;

/**
 * Cut by characters, not UTF-16 units: half an emoji is a lone surrogate,
 * which JSON.stringify writes as an escape the server refuses to parse.
 */
export function scrub(text: string, limit = MESSAGE_CHARS): string {
  const clean = text
    .replace(ADDRESS_TAIL, '$1')
    .replace(INIT_DATA, '')
    .replace(LONG_NUMBER, '…');
  return Array.from(clean).slice(0, limit).join('');
}

/**
 * A call's endpoint as a pattern: `/api/v1/helpers/:id` for any helper. A
 * number is an id, and so is a longer segment with a digit in it or one too
 * long to be a word; `v1` is neither.
 */
export function endpointOf(url: string): string {
  const path = url.replace(/^https?:\/\/[^/]+/, '').replace(/[?#].*$/, '');
  return path
    .split('/')
    .map((segment) => (isId(segment) ? ':id' : segment))
    .join('/')
    .slice(0, 120);
}

function isId(segment: string): boolean {
  return (
    /^-?\d+$/.test(segment) ||
    (/\d/.test(segment) && segment.length >= 6) ||
    segment.length > 32
  );
}

/** What to say about something thrown, and whether it is worth saying at all. */
export function describeError(error: unknown): {
  message: string;
  stack?: string;
  ignore: boolean;
} {
  if (error instanceof Error || error instanceof DOMException) {
    return {
      message: scrub(`${error.name}: ${error.message}`),
      stack: error.stack ? scrub(error.stack, STACK_CHARS) : undefined,
      // A request cancelled on purpose: a screen left, a query superseded.
      ignore: error.name === 'AbortError',
    };
  }
  return { message: scrub(String(error)), ignore: false };
}

/**
 * The app is a fraction of the window it is in: what a stale viewport height
 * looks like (docs/invariants.md, «Mini App»). Below 40%, because an open
 * keyboard shrinks the window too and the app with it.
 */
export function layoutLooksBroken(appHeight: number, windowHeight: number): boolean {
  return appHeight > 0 && windowHeight > 0 && appHeight < windowHeight * 0.4;
}

export interface Reporter {
  report(event: Omit<ClientEvent, 'route'> & { route?: string }): void;
  /** Send what is waiting now: the app is going away. */
  flush(): void;
}

export function createReporter({
  send,
  route,
}: {
  /**
   * `leaving` when the app is going away, which is when the request has to
   * outlive the page (`keepalive`). Only then: the browser caps what all such
   * requests in flight may carry together at 64 KiB, and a burst over it
   * would be dropped without a word.
   */
  send: (events: ClientEvent[], leaving: boolean) => void;
  route: () => string;
}): Reporter {
  const seen = new Set<string>();
  let queue: ClientEvent[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;

  const flush = (leaving: boolean): void => {
    clearTimeout(timer);
    timer = undefined;
    while (queue.length > 0) {
      const batch = queue.slice(0, PER_BATCH);
      queue = queue.slice(PER_BATCH);
      try {
        send(batch, leaving);
      } catch {
        // Reporting a failure to report would be a loop with no way out.
      }
    }
  };

  return {
    report(partial) {
      const event: ClientEvent = {
        ...partial,
        route: partial.route ?? route(),
        ...(partial.message === undefined ? {} : { message: scrub(partial.message) }),
      };
      const key = [
        event.kind,
        event.message,
        event.route,
        event.endpoint,
        event.status,
      ].join('|');
      if (seen.has(key) || seen.size >= PER_SESSION) return;
      seen.add(key);
      queue.push(event);
      timer ??= setTimeout(() => flush(false), FLUSH_MS);
    },
    flush: () => flush(true),
  };
}

/** The one reporter, once `startReporting` has made it; until then nothing is said. */
let current: Reporter | undefined;

export function startReporting(reporter: Reporter): void {
  current = reporter;
}

/** Send what is waiting now: the app is going away, or never started. */
export function flushClientEvents(): void {
  current?.flush();
}

export function reportClientEvent(
  event: Omit<ClientEvent, 'route'> & { route?: string },
): void {
  current?.report(event);
}

/**
 * Whether a call's status is a failure rather than an answer: nothing came
 * back (0), the server broke (5xx), or the signature was refused (401), which
 * locks somebody out of every screen. The other 4xx are the API saying no on
 * purpose — a profile not published yet, a request already closed — and the
 * screens say so to the reader.
 */
export function isFailure(status: number): boolean {
  return status === 0 || status === 401 || status >= 500;
}

/** A failed call to one of our APIs: its pattern and status, never its body. */
export function reportApiFailure(url: string, status: number): void {
  if (isFailure(status))
    reportClientEvent({ kind: 'api', endpoint: endpointOf(url), status });
}
