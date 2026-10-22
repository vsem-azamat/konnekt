/*
 * The layout on the phones Telegram actually runs on.
 *
 * check-scroll measures the app under the development mock,
 * which reports `tdesktop`. There the SDK derives the viewport from
 * `window.innerHeight`, so Telegram's height and the webview's are always the
 * same number, and the bugs that live in the difference between them — the
 * last row under the tab bar, the empty list after a restore (#328) — cannot
 * happen. This check makes them able to happen.
 *
 * It runs the production build, not the dev server, behind a stand-in for
 * Telegram's native bridge: `TelegramWebviewProxy` is defined before the page
 * loads, and every request the SDK makes of the client (`web_app_request_*`)
 * is answered the way an iOS or Android client would, with a viewport height
 * the profile chooses. The API is stubbed with fixtures, so nothing needs a
 * backend or signed init data, and this can run in CI.
 *
 * What it asserts is geometric, against what the person can see — the smaller
 * of Telegram's height and the webview's:
 *
 *   - the tab bar sits flush on the visible bottom;
 *   - scrolled to the end, the last thing in the list ends above the tab bar
 *     and inside the visible area, in the directory and in a section;
 *   - the first thing on the screen clears the notch and Telegram's header;
 *   - nothing is wider than the screen;
 *   - an open sheet lies inside the visible area;
 *   - on iOS, with Telegram's bottom button up, the screen behind it ends
 *     above the button, and so does a sheet opened there;
 *   - on iOS, with the keyboard up, a sheet's field and its last button can
 *     be seen above the keyboard;
 *   - a screen opened from a scrolled list starts at its top, and Back
 *     returns to the list where it was left, even when the list has to be
 *     loaded again;
 *   - after a minimise and restore, the app is as tall as what is visible.
 *
 * The keyboard is the stand-in's too. A headless browser opens none, and on
 * iOS the keyboard shrinks only the visual viewport, so the stand-in replaces
 * `window.visualViewport` and shrinks it while a field has focus. What it
 * cannot do is the Android keyboard, which resizes the whole webview and is a
 * resize like any other.
 *
 * `pnpm build` first. BASE=<url> measures a server that is already running.
 */

import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

import { VIEWPORTS } from './lib/stack.mjs';

/**
 * A webview of `width × height` CSS px, inside which Telegram reports `tg` as
 * the app's height. `safe` is the device's inset, `content` Telegram's own
 * chrome over the page (fullscreen only).
 *
 * Android is measured on the short phones the other checks use, with
 * Telegram's height equal to the window, taller than it (Android reports its
 * swipe container, header included) and shorter than it (iOS with its bottom
 * button up), so a fix for one direction cannot break another.
 */
const PROFILES = [
  ...VIEWPORTS.flatMap(({ width, height }) =>
    [0, 100, -60].map((delta) => ({
      name: `android ${width}×${height}, Telegram ${delta > 0 ? '+' : ''}${delta}px`,
      platform: 'android',
      width,
      height,
      tg: height + delta,
      safe: { bottom: 24 },
    })),
  ),
  {
    name: 'ios 390, notch',
    platform: 'ios',
    width: 390,
    height: 844,
    tg: 844,
    safe: { top: 47, bottom: 34 },
    keyboard: 336,
  },
  {
    name: 'ios 390, fullscreen',
    platform: 'ios',
    width: 390,
    height: 844,
    tg: 844,
    safe: { top: 47, bottom: 34 },
    keyboard: 336,
    content: { top: 46 },
  },
  {
    name: 'ios 375, no notch',
    platform: 'ios',
    width: 375,
    height: 667,
    tg: 667,
    keyboard: 260,
  },
  // The smallest phone Telegram for iOS still runs on: a sheet with a field
  // does not fit above its keyboard, and has to scroll.
  {
    name: 'ios 320, small',
    platform: 'ios',
    width: 320,
    height: 568,
    tg: 568,
    keyboard: 253,
    pan: 152,
  },
];

/**
 * What Telegram for iOS takes off the height it reports while its bottom
 * button is up: the button lies over the bottom of the webview.
 */
const BOTTOM_BUTTON = 58;

/** Sub-pixel layout leaves fractions behind; a hidden row is never this small. */
const TOLERANCE = 1.5;

// ── fixtures ────────────────────────────────────────────────────────────

/**
 * A directory long enough to scroll at every size, and a section of it that
 * is too: a short section, a long one, then loose chats. The last chat of each
 * list is named, so the check can tell that the end of the list is what it is
 * looking at.
 */
const LAST_CHAT = 'Zz last fixture chat';
const SECTION = 'Fixture section';
const LAST_IN_SECTION = 'Zz last in section';
const CHATS = [
  { title: 'ČVUT', group: 'ČVUT', institution: 'cvut' },
  { title: 'ČVUT FIT', group: 'ČVUT', institution: 'cvut' },
  { title: 'ČVUT FEL', group: 'ČVUT', institution: 'cvut' },
  { title: 'ČVUT FS', group: 'ČVUT', institution: 'cvut' },
  ...Array.from({ length: 14 }, (_, i) => ({
    title: `Section chat ${i + 1}`,
    group: SECTION,
  })),
  { title: LAST_IN_SECTION, group: SECTION },
  ...Array.from({ length: 18 }, (_, i) => ({ title: `Fixture chat ${i + 1}` })),
  { title: LAST_CHAT },
].map((chat, i) => ({
  group: null,
  institution: null,
  activity: i % 3 === 0 ? 'active' : 'unknown',
  member_count: 100 + i * 37,
  is_forum: false,
  external: false,
  avatar: null,
  link: `https://t.me/fixture_chat_${i}`,
  ...chat,
}));

/** Somebody's page, long enough to scroll, with Telegram's bottom button to write to them. */
const HELPER = {
  user_id: 7,
  name: 'Fixture Helper',
  avatar: { id: 7, initials: 'FH', tone: 2, photo_url: null },
  affiliation: 'ČVUT FIT',
  about: 'Fixture about. '.repeat(40),
  headline: null,
  stats: [],
  offers: [],
  langs: ['ru'],
  work_format: 'online',
  place_note: 'Zz end of the fixture helper',
  free_slots: [],
  reviews: [],
  intro_context: {},
  telegram_url: 'https://t.me/fixture_helper',
};

/** A search that found nobody, so the request sheet is what the screen offers. */
const NOBODY = {
  total: 0,
  filters: {
    subject_id: 1,
    institution_id: 2,
    service_type_id: 3,
    max_price: null,
    langs: [],
    work_format: null,
  },
  // Every kind of chip but the budget, which the sheet then offers to add.
  chips: [
    { kind: 'subject', label: 'Matematická analýza 1', value: 1, confidence: 1 },
    {
      kind: 'institution',
      label: 'ČVUT Fakulta informačních technologií',
      value: 2,
      confidence: 1,
    },
    {
      kind: 'service_type',
      label: 'Doučování a příprava na zkoušku',
      value: 3,
      confidence: 1,
    },
  ],
  results: [],
};

const FIXTURES = {
  'GET /api/public/catalog': CHATS,
  'GET /api/v1/institutions': [],
  'GET /api/v1/helpers/7': HELPER,
  'GET /api/v1/search': NOBODY,
  'POST /api/public/seen': null,
  'POST /api/public/client-errors': null,
};

// ── the stand-in for Telegram ───────────────────────────────────────────

/**
 * Runs in the page before any of the app's code. Declared as a plain function
 * so Playwright can serialise it.
 */
function telegramBridge(profile) {
  const inset = (side) => ({ top: 0, bottom: 0, left: 0, right: 0, ...side });
  const state = {
    height: profile.tg,
    stable: profile.tg,
    width: profile.width,
    safe: inset(profile.safe),
    content: inset(profile.content),
  };
  const receive = (name, data) => {
    // The SDK defines this when it loads; a request is never earlier than that.
    window.Telegram?.WebView?.receiveEvent?.(name, data);
  };
  const viewport = () => ({
    height: state.height,
    width: state.width,
    is_expanded: true,
    is_state_stable: state.height === state.stable,
  });
  const answers = {
    // On iOS the button lies over the webview, and the height Telegram
    // reports leaves it out. Android shrinks the webview instead.
    web_app_setup_main_button: ({ is_visible }) => {
      if (profile.platform !== 'ios' || Boolean(is_visible) === window.__telegram.button)
        return;
      window.__telegram.button = Boolean(is_visible);
      state.height = state.stable = profile.tg - (is_visible ? profile.button : 0);
      receive('viewport_changed', viewport());
    },
    web_app_request_viewport: () => receive('viewport_changed', viewport()),
    web_app_request_safe_area: () => receive('safe_area_changed', state.safe),
    web_app_request_content_safe_area: () =>
      receive('content_safe_area_changed', state.content),
    web_app_request_theme: () =>
      receive('theme_changed', { theme_params: { bg_color: '#ffffff' } }),
  };
  window.TelegramWebviewProxy = {
    postEvent(name, data) {
      const answer = answers[name];
      // Asynchronously, as a real client does: the SDK subscribes after posting.
      if (answer) setTimeout(() => answer(data ? JSON.parse(data) : {}), 0);
    },
  };
  /** For the check: what Telegram would send when the sheet moves. */
  window.__telegram = {
    button: false,
    move(height, stable) {
      state.height = height;
      if (stable) state.stable = height;
      receive('viewport_changed', viewport());
    },
  };

  // The iOS keyboard: the layout keeps its height and the visual viewport
  // loses the keyboard's, for as long as a field has focus. With `pan`, iOS
  // has also moved the view that far down the window to show the field.
  if (!profile.keyboard) return;
  let covered = 0;
  let panned = 0;
  const visual = new EventTarget();
  for (const [key, get] of Object.entries({
    width: () => window.innerWidth,
    height: () => window.innerHeight - covered,
    offsetTop: () => panned,
    offsetLeft: () => 0,
    pageTop: () => panned,
    pageLeft: () => 0,
    scale: () => 1,
  })) {
    Object.defineProperty(visual, key, { get });
  }
  Object.defineProperty(window, 'visualViewport', { get: () => visual });
  const typing = (el) => el instanceof HTMLElement && el.matches('input, textarea');
  const show = (up) => {
    covered = up ? profile.keyboard : 0;
    panned = up ? (profile.pan ?? 0) : 0;
    visual.dispatchEvent(new Event('resize'));
  };
  document.addEventListener('focusin', (e) => typing(e.target) && show(true));
  document.addEventListener('focusout', (e) => typing(e.target) && show(false));
}

function launchHash(profile) {
  const initData = new URLSearchParams({
    user: JSON.stringify({ id: 1, first_name: 'Check', language_code: 'ru' }),
    auth_date: String(Math.floor(Date.now() / 1000)),
    hash: '0'.repeat(64),
    signature: 'check-devices',
  }).toString();
  return new URLSearchParams({
    tgWebAppData: initData,
    tgWebAppVersion: '9.0',
    tgWebAppPlatform: profile.platform,
    tgWebAppThemeParams: JSON.stringify({ bg_color: '#ffffff', text_color: '#000000' }),
  }).toString();
}

// ── measurements (run in the page) ──────────────────────────────────────

/**
 * Where everything is, with the scroller at its end.
 *
 * The scroller is found rather than named: the tallest element that scrolls
 * vertically, #root or the shell's `main`.
 */
function measureScreen() {
  const scrollers = [...document.querySelectorAll('*')].filter((el) => {
    const { overflowY } = getComputedStyle(el);
    return /(auto|scroll)/.test(overflowY) && el.scrollHeight > el.clientHeight + 1;
  });
  const scroller =
    scrollers.sort((a, b) => b.clientHeight - a.clientHeight)[0] ??
    document.getElementById('root');
  scroller.scrollTop = scroller.scrollHeight;

  const bar = document.querySelector('nav');
  const barBox = bar?.getBoundingClientRect() ?? null;

  /** Text and pictures in the list: what a person would miss if it were hidden. */
  let lowest = null;
  for (const el of scroller.querySelectorAll('*')) {
    if (bar?.contains(el) || el.closest('[role="dialog"]')) continue;
    if (getComputedStyle(el).position === 'fixed') continue;
    const own = [...el.childNodes].some(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim(),
    );
    if (!own && !/^(img|svg|input|textarea)$/i.test(el.tagName)) continue;
    if (!el.checkVisibility({ opacityProperty: true, visibilityProperty: true }))
      continue;
    const box = el.getBoundingClientRect();
    if (box.height <= 0) continue;
    if (!lowest || box.bottom > lowest.bottom) {
      lowest = {
        bottom: box.bottom,
        text: (el.textContent ?? el.tagName).trim().slice(0, 40),
      };
    }
  }

  return {
    innerHeight: window.innerHeight,
    innerWidth: window.innerWidth,
    docWidth: document.documentElement.scrollWidth,
    scrollerWidth: scroller.scrollWidth - scroller.clientWidth,
    bar: barBox && { top: barBox.top, bottom: barBox.bottom },
    lowest,
  };
}

function measureTop() {
  const scroller = document.getElementById('root');
  for (const el of document.querySelectorAll('#root *')) el.scrollTop = 0;
  scroller.scrollTop = 0;
  let highest = null;
  for (const el of scroller.querySelectorAll('h1, h2, p, span, button, input')) {
    if (el.closest('nav') || el.closest('[role="dialog"]')) continue;
    const box = el.getBoundingClientRect();
    if (box.height <= 0 || !el.checkVisibility()) continue;
    if (!highest || box.top < highest.top)
      highest = { top: box.top, text: el.textContent?.trim().slice(0, 30) };
  }
  return highest;
}

// ── running it ──────────────────────────────────────────────────────────

const failures = [];
const fail = (profile, what) => {
  failures.push(`${profile.name}: ${what}`);
  console.log(`  FAIL ${what}`);
};
const ok = (what) => console.log(`  ok   ${what}`);

async function serve() {
  if (process.env.BASE) return { base: process.env.BASE, stop: () => {} };
  const port = 4321;
  const server = spawn(
    'pnpm',
    [
      'exec',
      'vite',
      'preview',
      '--host',
      '127.0.0.1',
      '--port',
      String(port),
      '--strictPort',
    ],
    {
      stdio: ['ignore', 'inherit', 'inherit'],
      env: { ...process.env, VITE_NO_HTTPS: '1' },
    },
  );
  const base = `http://127.0.0.1:${port}`;
  const stop = () => server.kill();
  let exited = null;
  server.on('exit', (code) => {
    exited = code;
  });
  // Asked rather than read from its output: under CI the port is printed in
  // colour, and a wait for plain text then never ends.
  const deadline = Date.now() + 30_000;
  for (;;) {
    if (exited !== null) {
      throw new Error(
        `vite preview exited with ${exited}: port ${port} busy, or no build`,
      );
    }
    if (Date.now() > deadline) {
      stop();
      throw new Error(`vite preview did not answer on ${base} within 30s`);
    }
    try {
      if ((await fetch(base)).ok) return { base, stop };
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
}

async function open(
  browser,
  base,
  profile,
  path,
  { slowCatalog = false, clock = false } = {},
) {
  const context = await browser.newContext({
    viewport: { width: profile.width, height: profile.height },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  await context.addInitScript(telegramBridge, { button: BOTTOM_BUTTON, ...profile });
  const unknown = new Set();
  let catalogCalls = 0;
  await context.route('**/api/**', async (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
    // Asked again after the cache dropped it: the screen is a skeleton first.
    if (key === 'GET /api/public/catalog' && slowCatalog && catalogCalls++ > 0) {
      await new Promise((resolve) => setTimeout(resolve, 600));
    }
    if (key in FIXTURES) {
      const body = FIXTURES[key];
      return body === null
        ? route.fulfill({ status: 204 })
        : route.fulfill({ json: body });
    }
    unknown.add(key);
    return route.fulfill({ status: 404, json: { detail: 'no fixture' } });
  });
  const page = await context.newPage();
  if (clock) await page.clock.install();
  await page.goto(`${base}${path}#${launchHash(profile)}`);
  return { page, context, unknown };
}

/** The visible bottom: the smaller of what Telegram reports and what the webview has. */
const visibleBottom = (profile, height = profile.tg, inner = profile.height) =>
  Math.min(height, inner);

/** The directory and a section of it, both under the tab bar. */
const LISTS = [
  { path: '/chats', last: LAST_CHAT },
  { path: `/chats/${encodeURIComponent(SECTION)}`, last: LAST_IN_SECTION },
];

async function checkList(browser, base, profile, { path, last }) {
  const { page, context, unknown } = await open(browser, base, profile, path);
  try {
    await page.getByText(last).waitFor({ timeout: 10_000 });
  } catch {
    fail(
      profile,
      `${path} never showed its list (no fixture for: ${[...unknown].join(', ') || 'none'})`,
    );
    await context.close();
    return;
  }
  await page.waitForTimeout(400); // past appHeight's settle

  const top = await page.evaluate(measureTop);
  const clearance = (profile.safe?.top ?? 0) + (profile.content?.top ?? 0);
  if (top && top.top < clearance - TOLERANCE) {
    fail(
      profile,
      `${path}: «${top.text}» starts at ${Math.round(top.top)}px, under the ${clearance}px inset`,
    );
  } else ok(`${path}: top clears ${clearance}px`);

  const seen = await page.evaluate(measureScreen);
  const bottom = visibleBottom(profile);

  if (seen.docWidth > seen.innerWidth || seen.scrollerWidth > 1) {
    fail(
      profile,
      `${path}: wider than the screen (${seen.docWidth}px in ${seen.innerWidth}px)`,
    );
  } else ok(`${path}: no sideways scroll`);

  if (!seen.bar) {
    fail(profile, `${path}: no tab bar`);
  } else if (Math.abs(seen.bar.bottom - bottom) > TOLERANCE) {
    fail(
      profile,
      `${path}: tab bar ends at ${Math.round(seen.bar.bottom)}px, the visible bottom is ${bottom}px`,
    );
  } else ok(`${path}: tab bar flush on the visible bottom (${bottom}px)`);

  if (!seen.lowest) {
    fail(profile, `${path}: nothing in the list to measure`);
  } else {
    const limit = Math.min(seen.bar?.top ?? bottom, bottom);
    const under = seen.lowest.bottom - limit;
    if (under > TOLERANCE) {
      fail(
        profile,
        `${path}: scrolled to the end, «${seen.lowest.text}» is ${Math.round(under)}px under the tab bar or the visible bottom`,
      );
    } else ok(`${path}: the end of the list is visible`);
  }

  if (path !== '/chats') {
    await context.close();
    return;
  }

  // A chat's preview: the sheet has to be on the screen.
  await page.getByText(last).click();
  const dialog = page.getByRole('dialog');
  try {
    await dialog.waitFor({ timeout: 3000 });
    await page.waitForTimeout(300); // the rise animation
    const box = await dialog.boundingBox();
    if (box.y < clearance - TOLERANCE || box.y + box.height > bottom + TOLERANCE) {
      fail(
        profile,
        `chat sheet spans ${Math.round(box.y)}–${Math.round(box.y + box.height)}px, visible is ${clearance}–${bottom}px`,
      );
    } else ok('chat sheet inside the visible area');
  } catch {
    fail(profile, 'tapping a chat opened no sheet');
  }

  await context.close();
}

/** How far the screen's list is scrolled: the tallest element that scrolls. */
function scrolled() {
  const scrollers = [...document.querySelectorAll('*')].filter((el) => {
    const { overflowY } = getComputedStyle(el);
    return /(auto|scroll)/.test(overflowY) && el.scrollHeight > el.clientHeight + 1;
  });
  const scroller = scrollers.sort((a, b) => b.clientHeight - a.clientHeight)[0];
  return scroller ? scroller.scrollTop : 0;
}

/**
 * A screen opened from a scrolled list starts at its top, and Back returns to
 * the list where it was left. One scroller shared by every screen kept its
 * position across the navigation instead: the section opened at its end.
 */
async function checkNavigation(browser, base, profile) {
  const { page, context } = await open(browser, base, profile, '/chats');
  try {
    await page.getByText(LAST_CHAT).waitFor({ timeout: 10_000 });
    await page.waitForTimeout(400);
    // Scrolled to the row first: a click would scroll to it by itself, after
    // the position was taken.
    const row = page.getByText(SECTION, { exact: true }).first();
    await row.evaluate((el) => el.scrollIntoView({ block: 'start' }));
    const left = await page.evaluate(scrolled);
    if (left <= 0) throw new Error('the list did not scroll, so nothing is measured');
    await row.click();
    await page.getByText(LAST_IN_SECTION).waitFor({ timeout: 5000 });
    await page.waitForTimeout(200);
    const opened = await page.evaluate(scrolled);
    if (opened > TOLERANCE) {
      fail(profile, `a section opened from the scrolled list starts ${opened}px down`);
    } else ok('a screen opened from a scrolled list starts at its top');
    await page.goBack();
    await page.getByText(LAST_CHAT).waitFor({ timeout: 5000 });
    await page.waitForTimeout(200);
    const back = await page.evaluate(scrolled);
    if (Math.abs(back - left) > TOLERANCE) {
      fail(profile, `Back returned to the list at ${back}px, it was left at ${left}px`);
    } else ok('Back returns to the list where it was left');
  } catch (error) {
    fail(profile, `navigation: ${error.message.split('\n')[0]}`);
  }
  await context.close();
}

/**
 * Back from a screen without tabs after the list's data has gone from the
 * cache (five minutes unused): the list comes back as a skeleton first, and
 * the position has to survive until the rows arrive.
 */
async function checkReturn(browser, base, profile) {
  const { page, context } = await open(browser, base, profile, '/chats', {
    slowCatalog: true,
    clock: true,
  });
  try {
    await page.getByText(LAST_CHAT).waitFor({ timeout: 10_000 });
    await page.waitForTimeout(400);
    const row = page.getByText(SECTION, { exact: true }).first();
    await row.evaluate((el) => el.scrollIntoView({ block: 'start' }));
    const left = await page.evaluate(scrolled);
    if (left <= 0) throw new Error('the list did not scroll, so nothing is measured');
    await page.getByRole('button', { name: 'Разместить' }).click();
    await page.getByRole('dialog').getByRole('button').first().click();
    await page.waitForURL('**/ask**');
    await page.clock.fastForward('06:00');
    await page.goBack();
    await page.getByText(LAST_CHAT).waitFor({ timeout: 10_000 });
    await page.waitForTimeout(300);
    const back = await page.evaluate(scrolled);
    if (Math.abs(back - left) > TOLERANCE) {
      fail(
        profile,
        `Back after six minutes away returned to the list at ${back}px, it was left at ${left}px`,
      );
    } else ok('Back after six minutes away returns to where the list was left');
  } catch (error) {
    fail(profile, `return: ${error.message.split('\n')[0]}`);
  }
  await context.close();
}

/**
 * Minimised to the bottom bar and brought back, in the order #328 was seen in:
 * a stable height for the bar, then only moving heights on the way back up.
 */
async function checkRestore(browser, base, profile) {
  const { page, context } = await open(browser, base, profile, '/chats');
  await page
    .getByText(LAST_CHAT)
    .waitFor({ timeout: 10_000 })
    .catch(() => {});
  await page.evaluate((tg) => {
    window.__telegram.move(56, true);
    window.__telegram.move(Math.round(tg / 2), false);
    window.__telegram.move(tg, false);
  }, profile.tg);
  await page.waitForTimeout(600);
  const height = await page.evaluate(
    () => document.getElementById('root').getBoundingClientRect().height,
  );
  const visible = visibleBottom(profile);
  if (Math.abs(height - visible) > TOLERANCE) {
    fail(
      profile,
      `after a restore the app is ${Math.round(height)}px, ${visible}px is visible`,
    );
  } else ok('restore: app back to full height');
  await context.close();
}

/** Where a box lies against what can be seen: an empty string when inside. */
function outside(box, top, bottom) {
  const end = box.y + box.height;
  if (box.y >= top - TOLERANCE && end <= bottom + TOLERANCE) return '';
  return `spans ${Math.round(box.y)}–${Math.round(end)}px, visible is ${top}–${bottom}px`;
}

/**
 * A screen with Telegram's bottom button, on iOS: the button covers the bottom
 * of the webview, and the screen and the sheet over it end above it.
 */
async function checkBottomButton(browser, base, profile) {
  const { page, context } = await open(browser, base, profile, '/helper/7');
  try {
    await page.getByText(HELPER.place_note).waitFor({ timeout: 10_000 });
    await page.waitForTimeout(400);
    if (!(await page.evaluate(() => window.__telegram.button))) {
      throw new Error('the screen never asked for the bottom button');
    }
    const bottom = visibleBottom(profile, profile.tg - BOTTOM_BUTTON);
    const clearance = (profile.safe?.top ?? 0) + (profile.content?.top ?? 0);
    const seen = await page.evaluate(measureScreen);
    const under = (seen.lowest?.bottom ?? Infinity) - bottom;
    if (under > TOLERANCE) {
      fail(
        profile,
        `bottom button: scrolled to the end, «${seen.lowest?.text}» is ${Math.round(under)}px under it`,
      );
    } else ok('bottom button: the end of the screen is above it');

    await page.getByRole('button', { name: 'Язык приложения' }).click();
    const dialog = page.getByRole('dialog');
    await dialog.waitFor({ timeout: 3000 });
    await page.waitForTimeout(300);
    const where = outside(await dialog.boundingBox(), clearance, bottom);
    if (where) fail(profile, `bottom button: the sheet ${where}`);
    else ok('bottom button: a sheet opened there is above it');
  } catch (error) {
    fail(profile, `bottom button: ${error.message.split('\n')[0]}`);
  }
  await context.close();
}

/**
 * The request sheet with the keyboard up, on iOS: what is typed into, and the
 * button that sends it, can be seen above the keyboard. Twice: in the field at
 * the top of the sheet, and in the budget at its end, which the shrinking
 * sheet would otherwise leave below its scroll. With `pan`, iOS has moved the
 * view down the window to the field, and the top of the window is out of
 * sight too.
 */
async function checkKeyboard(browser, base, profile, pan = 0) {
  const { page, context } = await open(
    browser,
    base,
    { ...profile, pan },
    `/results?q=${encodeURIComponent('matan na FIT')}&subject_id=1&institution_id=2&service_type_id=3&ask=1`,
  );
  const as = pan ? `keyboard, view panned ${pan}px` : 'keyboard';
  const top = pan + (profile.safe?.top ?? 0) + (profile.content?.top ?? 0);
  const bottom = pan + visibleBottom(profile) - profile.keyboard;
  const dialog = page.getByRole('dialog');
  const seen = async (locator, what) => {
    const where = outside(await locator.boundingBox(), top, bottom);
    if (where) fail(profile, `${as}: ${what} ${where}`);
    else ok(`${as}: ${what} can be seen`);
  };
  try {
    const field = dialog.locator('textarea');
    await field.waitFor({ timeout: 10_000 });
    await page.waitForTimeout(400);
    await field.click();
    await page.waitForTimeout(300);
    await seen(dialog.locator('span').first(), 'the top of the sheet');
    await seen(field, 'the field');

    // Scrolled to inside the sheet, without the click that would do it.
    const send = dialog.getByRole('button').last();
    await send.evaluate((el) => el.scrollIntoView({ block: 'nearest' }));
    await page.waitForTimeout(100);
    await seen(send, "the sheet's last button");

    // Keyboard down, the budget added, and the keyboard up again for it.
    await field.blur();
    await page.waitForTimeout(200);
    await dialog.getByRole('button', { name: '+ бюджет' }).click();
    const budget = dialog.locator('input');
    await budget.click();
    await page.waitForTimeout(300);
    await seen(budget, 'the budget field');
  } catch (error) {
    fail(profile, `${as}: ${error.message.split('\n')[0]}`);
  }
  await context.close();
}

const { base, stop } = await serve();
let browser;
try {
  browser = await chromium.launch();
  for (const profile of PROFILES) {
    console.log(
      `\n${profile.name} (${profile.width}×${profile.height}, Telegram ${profile.tg}px)`,
    );
    for (const list of LISTS) await checkList(browser, base, profile, list);
    await checkNavigation(browser, base, profile);
    await checkReturn(browser, base, profile);
    if (profile.platform === 'android') {
      await checkRestore(browser, base, profile);
    } else {
      await checkBottomButton(browser, base, profile);
      if (profile.keyboard) await checkKeyboard(browser, base, profile);
      if (profile.pan) await checkKeyboard(browser, base, profile, profile.pan);
    }
  }
} finally {
  await browser?.close();
  stop();
}

if (failures.length) {
  console.error(`\n${failures.length} layout failure(s):\n  ${failures.join('\n  ')}`);
  process.exit(1);
}
console.log('\nEvery profile lays out inside what Telegram shows.');
