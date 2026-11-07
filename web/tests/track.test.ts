import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  createTracker,
  FLUSH_MS,
  HEARTBEAT_MS,
  PER_BATCH,
  SESSION_GAP_MS,
  type TrackedEvent,
} from '../src/lib/track.ts';

/** A clock and timers the test moves by hand. */
function setup() {
  let now = 1_000_000;
  let ids = 0;
  const timers = new Map<number, { at: number; fn: () => void }>();
  let next = 0;
  const sent: TrackedEvent[][] = [];
  const leavings: boolean[] = [];
  const tracker = createTracker({
    send: (events, leaving) => {
      sent.push(events);
      leavings.push(leaving);
    },
    route: () => '/home',
    now: () => now,
    newId: () => `session-${++ids}`,
    setTimer: (fn, ms) => {
      timers.set(++next, { at: now + ms, fn });
      return next;
    },
    clearTimer: (handle) => {
      timers.delete(handle as number);
    },
  });
  const advance = (ms: number) => {
    const end = now + ms;
    for (;;) {
      const due = [...timers.entries()]
        .filter(([, t]) => t.at <= end)
        .sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      timers.delete(due[0]);
      now = due[1].at;
      due[1].fn();
    }
    now = end;
  };
  const names = () => sent.flat().map((event) => event.name);
  return { tracker, sent, leavings, advance, names };
}

test('a launch starts a session, and events wait a moment and go out together', () => {
  const { tracker, sent, advance } = setup();
  tracker.track('tab_tap', { tab: 'chats' });
  assert.equal(sent.length, 0);
  advance(FLUSH_MS);
  assert.deepEqual(
    (sent[0] ?? []).map((e) => [e.name, e.seq, e.session, e.screen]),
    [
      ['session_start', 0, 'session-1', '/home'],
      ['tab_tap', 1, 'session-1', '/home'],
    ],
  );
});

test('the app beats every half minute while on screen, and not while put away', () => {
  const { tracker, advance, names } = setup();
  advance(HEARTBEAT_MS * 2);
  tracker.visible(false);
  advance(HEARTBEAT_MS * 3);
  assert.equal(names().filter((n) => n === 'heartbeat').length, 2);
});

test('put away, what waits goes at once and is allowed to outlive the page', () => {
  const { tracker, leavings } = setup();
  tracker.visible(false);
  assert.deepEqual(leavings, [true]);
});

test('back after a long break is a new session; after a short one, the same', () => {
  const { tracker, sent, advance } = setup();
  tracker.visible(false);
  advance(SESSION_GAP_MS - 1000);
  tracker.visible(true);
  tracker.visible(false);
  advance(SESSION_GAP_MS + 1000);
  tracker.visible(true);
  tracker.flush();
  const starts = sent.flat().filter((e) => e.name === 'session_start');
  assert.deepEqual(
    starts.map((e) => [e.session, e.props]),
    [
      ['session-1', {}],
      ['session-2', { resumed: true }],
    ],
  );
});

test('a word that is not ours never leaves the phone', () => {
  const { tracker, sent } = setup();
  tracker.track('chat_open', { section: 'ČVUT Praha' });
  tracker.track('search_submit', { results: -1, filters: 2 });
  tracker.flush();
  const [, chat, search] = sent.flat();
  assert.deepEqual(chat?.props, {});
  assert.deepEqual(search?.props, { filters: 2 });
});

test('turned off, nothing is counted and nothing waiting is sent', () => {
  const { tracker, sent, advance } = setup();
  tracker.track('tab_tap', { tab: 'chats' });
  tracker.setEnabled(false);
  tracker.track('tab_tap', { tab: 'home' });
  advance(HEARTBEAT_MS * 4);
  tracker.flush();
  assert.equal(sent.length, 0);
});

test('a busy minute goes out in batches the server accepts', () => {
  const { tracker, sent } = setup();
  for (let i = 0; i < PER_BATCH * 2; i++)
    tracker.track('filter_change', { filter: 'sort' });
  tracker.flush();
  assert.ok(sent.every((batch) => batch.length <= PER_BATCH));
  assert.equal(sent.flat().length, PER_BATCH * 2 + 1);
});
