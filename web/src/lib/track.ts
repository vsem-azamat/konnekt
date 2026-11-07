/**
 * What people do in the app, for the console's «Использование».
 *
 * One call, `track(name, props)`, for every screen and button; one list of
 * names, `EventProps`, which is the server's `app/usage/events.py` in
 * TypeScript. A name or a property the server does not know is dropped there
 * and counted, so the two lists cannot drift without it showing.
 *
 * A property is a number, a yes or no, or a word of ours: never text a person
 * typed and never an id. The screen is its route pattern (`/helper/:id`),
 * never its address.
 *
 * Sessions are counted from a heartbeat, every half minute while the app is
 * on screen and never while it is put away: closing Telegram gives the app no
 * chance to say goodbye, so nothing here relies on one. Back after a break
 * longer than `SESSION_GAP_MS`, it is a new session.
 *
 * Nothing about this is kept on the device but the session id, in memory.
 * Somebody who turns counting off in the profile is not counted from then on:
 * the choice lives in Telegram's cloud storage for this bot, so it follows
 * them to every device, and the app checks it before it sends anything.
 */

/** A word of ours, as the server checks it: a tab, a section, where a tap came from. */
type Word = string;

export interface EventProps {
  session_start: { resumed?: boolean };
  heartbeat: Record<string, never>;
  screen_view: Record<string, never>;
  tab_tap: { tab: Word };
  search_submit: { results: number; filters: number };
  filter_change: { filter: Word };
  helper_open: { from: Word };
  contact_tap: { from: Word };
  offer_start: { from: Word };
  request_send: Record<string, never>;
  chat_open: { section: Word };
  partner_tap: { from: Word };
}

export type EventName = keyof EventProps;

export interface TrackedEvent {
  name: EventName;
  at: number;
  seq: number;
  session: string;
  screen?: string;
  props: Record<string, string | number | boolean>;
}

export const HEARTBEAT_MS = 30_000;
/** Away longer than this, and coming back is a new session. The server reads sessions the same way. */
export const SESSION_GAP_MS = 2 * 60_000;
/** How long events wait for company before they go. */
export const FLUSH_MS = 10_000;
/** Events per request, the server's cap. */
export const PER_BATCH = 50;
/** Events waiting at most; past that the oldest go, so a dead network cannot grow the queue. */
const MAX_WAITING = 500;
/** The cloud-storage key for «do not count me». */
export const OPT_OUT_KEY = 'usage_off';

/** Our own words, as the server accepts them. */
const WORD = /^[a-z0-9_:-]{1,32}$/;

export interface TrackerDeps {
  /** `leaving` when the app is going away, which is when a request has to outlive the page. */
  send: (events: TrackedEvent[], leaving: boolean) => void;
  /** The current screen's route pattern. */
  route: () => string;
  now: () => number;
  newId: () => string;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
}

export interface Tracker {
  track<N extends EventName>(name: N, props: EventProps[N]): void;
  /** The app came on screen, or went away. */
  visible(isVisible: boolean): void;
  /** Send what is waiting now: the app is going away. */
  flush(): void;
  /** Stop counting and forget what is waiting, or start again. */
  setEnabled(enabled: boolean): void;
}

export function createTracker(deps: TrackerDeps): Tracker {
  let enabled = true;
  let session = deps.newId();
  let seq = 0;
  let hiddenAt: number | null = null;
  let queue: TrackedEvent[] = [];
  let flushTimer: unknown;
  let beat: unknown;

  const flush = (leaving: boolean): void => {
    if (flushTimer !== undefined) deps.clearTimer(flushTimer);
    flushTimer = undefined;
    while (queue.length > 0) {
      const batch = queue.slice(0, PER_BATCH);
      queue = queue.slice(PER_BATCH);
      try {
        deps.send(batch, leaving);
      } catch {
        // Counting must never break the app.
      }
    }
  };

  const push = (
    name: EventName,
    props: Record<string, string | number | boolean>,
  ): void => {
    if (!enabled) return;
    queue.push({
      name,
      at: deps.now(),
      seq: seq++,
      session,
      screen: deps.route(),
      props: clean(props),
    });
    if (queue.length > MAX_WAITING) queue = queue.slice(-MAX_WAITING);
    if (queue.length >= PER_BATCH) flush(false);
    else flushTimer ??= deps.setTimer(() => flush(false), FLUSH_MS);
  };

  const startBeating = (): void => {
    if (beat !== undefined) return;
    const tick = (): void => {
      push('heartbeat', {});
      beat = deps.setTimer(tick, HEARTBEAT_MS);
    };
    beat = deps.setTimer(tick, HEARTBEAT_MS);
  };

  const stopBeating = (): void => {
    if (beat !== undefined) deps.clearTimer(beat);
    beat = undefined;
  };

  push('session_start', {});
  startBeating();

  return {
    track(name, props) {
      push(name, props as Record<string, string | number | boolean>);
    },
    visible(isVisible) {
      if (!isVisible) {
        hiddenAt ??= deps.now();
        stopBeating();
        flush(true);
        return;
      }
      if (hiddenAt !== null && deps.now() - hiddenAt > SESSION_GAP_MS) {
        session = deps.newId();
        seq = 0;
        push('session_start', { resumed: true });
      }
      hiddenAt = null;
      startBeating();
    },
    flush: () => flush(true),
    setEnabled(next) {
      enabled = next;
      if (!next) {
        queue = [];
        stopBeating();
      } else startBeating();
    },
  };
}

/** Only what the server takes: a word that is not ours is dropped here rather than costing the event there. */
function clean(
  props: Record<string, string | number | boolean>,
): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {};
  for (const [key, value] of Object.entries(props)) {
    if (typeof value === 'string' && !WORD.test(value)) continue;
    if (typeof value === 'number' && !(Number.isInteger(value) && value >= 0)) continue;
    out[key] = value;
  }
  return out;
}

/** The one tracker, once `startTracking` has made it. */
let current: Tracker | undefined;
/**
 * Events from before the choice was read: a screen opened by a launch link
 * says so at once. Kept until the answer, then counted or forgotten.
 */
let waiting: [EventName, EventProps[EventName]][] | null = [];
const MAX_EARLY = 20;

export function startTracking(tracker: Tracker): void {
  current = tracker;
  for (const [name, props] of waiting ?? []) tracker.track(name, props);
  waiting = null;
}

/** Counting is off for this launch: forget what waited for the answer. */
export function stopWaiting(): void {
  waiting = null;
}

export function track<N extends EventName>(name: N, props: EventProps[N]): void {
  if (current) current.track(name, props);
  else if (waiting && waiting.length < MAX_EARLY) waiting.push([name, props]);
}

export function setTracking(enabled: boolean): void {
  current?.setEnabled(enabled);
}

/** The last two screens, so a screen can say which one led to it. */
let screens: [string, string] = ['', ''];

export function noteScreen(pattern: string): void {
  screens = [screens[1], pattern];
}

/** The screen before this one as a word of ours: `/request/:id` is `request`. */
export function cameFrom(): string {
  const first = screens[0].split('/')[1] ?? '';
  return WORD.test(first) ? first : 'other';
}
