/*
 * The layout on the phones Telegram actually runs on.
 *
 * check-scroll and check-tabbar measure the app under the development mock,
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
 *   - the tab bar sits flush on the visible bottom, inside it;
 *   - scrolled to the end, the last thing in the list ends above the tab bar
 *     (or above the bottom inset where there is no bar);
 *   - the first thing on the screen clears the notch and Telegram's header;
 *   - nothing is wider than the screen;
 *   - an open sheet lies inside the visible area;
 *   - after a minimise and restore, the app is as tall as what is visible.
 *
 * What it cannot do: an iOS keyboard shrinks only the visual viewport, which a
 * headless browser does not emulate, so the keyboard case is Android's, where
 * the webview itself is resized.
 *
 * `pnpm build` first. BASE=<url> measures a server that is already running.
 */

import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

/**
 * A webview of `width × height` CSS px, inside which Telegram reports `tg` as
 * the app's height. `safe` is the device's inset, `content` Telegram's own
 * chrome over the page (fullscreen only).
 */
const PROFILES = [
  { name: 'android 360, equal', platform: 'android', width: 360, height: 640, tg: 640 },
  {
    name: 'android 412, Telegram shorter',
    platform: 'android',
    width: 412,
    height: 915,
    tg: 867,
    safe: { bottom: 24 },
  },
  {
    name: 'android 412, Telegram taller',
    platform: 'android',
    width: 412,
    height: 867,
    tg: 915,
    safe: { bottom: 24 },
  },
  {
    name: 'ios 390, notch',
    platform: 'ios',
    width: 390,
    height: 844,
    tg: 844,
    safe: { top: 47, bottom: 34 },
  },
  {
    name: 'ios 390, fullscreen',
    platform: 'ios',
    width: 390,
    height: 844,
    tg: 844,
    safe: { top: 47, bottom: 34 },
    content: { top: 46 },
  },
  { name: 'ios 375, no notch', platform: 'ios', width: 375, height: 667, tg: 667 },
];

/** Sub-pixel layout leaves fractions behind; a hidden row is never this small. */
const TOLERANCE = 1.5;

// ── fixtures ────────────────────────────────────────────────────────────

/**
 * A directory long enough to scroll at every size: one section with its own
 * chat and three more, then loose chats. The last one is named, so the check
 * can tell that the end of the list is what it is looking at.
 */
const LAST_CHAT = 'Zz last fixture chat';
const CHATS = [
  { title: 'ČVUT', group: 'ČVUT', institution: 'cvut' },
  { title: 'ČVUT FIT', group: 'ČVUT', institution: 'cvut' },
  { title: 'ČVUT FEL', group: 'ČVUT', institution: 'cvut' },
  { title: 'ČVUT FS', group: 'ČVUT', institution: 'cvut' },
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

const FIXTURES = {
  'GET /api/public/catalog': CHATS,
  'GET /api/v1/institutions': [],
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
    web_app_request_viewport: () => receive('viewport_changed', viewport()),
    web_app_request_safe_area: () => receive('safe_area_changed', state.safe),
    web_app_request_content_safe_area: () =>
      receive('content_safe_area_changed', state.content),
    web_app_request_theme: () =>
      receive('theme_changed', { theme_params: { bg_color: '#ffffff' } }),
  };
  window.TelegramWebviewProxy = {
    postEvent(name) {
      const answer = answers[name];
      // Asynchronously, as a real client does: the SDK subscribes after posting.
      if (answer) setTimeout(answer, 0);
    },
  };
  /** For the check: what Telegram would send when the sheet moves. */
  window.__telegram = {
    move(height, stable) {
      state.height = height;
      if (stable) state.stable = height;
      receive('viewport_changed', viewport());
    },
  };
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
 * vertically. Today that is #root; after a shell refactor it may be a `main`
 * inside it, and this should not have to change with it.
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
    { stdio: ['ignore', 'pipe', 'inherit'], env: { ...process.env, VITE_NO_HTTPS: '1' } },
  );
  await new Promise((resolve, reject) => {
    server.stdout.on('data', (chunk) => {
      if (String(chunk).includes(`:${port}`)) resolve();
    });
    server.on('exit', (code) =>
      reject(new Error(`vite preview exited with ${code}; run pnpm build first`)),
    );
  });
  return { base: `http://127.0.0.1:${port}`, stop: () => server.kill() };
}

async function open(browser, base, profile, path) {
  const context = await browser.newContext({
    viewport: { width: profile.width, height: profile.height },
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
  });
  await context.addInitScript(telegramBridge, profile);
  const unknown = new Set();
  await context.route('**/api/**', (route) => {
    const request = route.request();
    const key = `${request.method()} ${new URL(request.url()).pathname}`;
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
  await page.goto(`${base}${path}#${launchHash(profile)}`);
  return { page, context, unknown };
}

/** The visible bottom: the smaller of what Telegram reports and what the webview has. */
const visibleBottom = (profile, height = profile.tg, inner = profile.height) =>
  Math.min(height, inner);

async function checkList(browser, base, profile) {
  const { page, context, unknown } = await open(browser, base, profile, '/chats');
  try {
    await page.getByText(LAST_CHAT).waitFor({ timeout: 10_000 });
  } catch {
    fail(
      profile,
      `/chats never showed its list (no fixture for: ${[...unknown].join(', ') || 'none'})`,
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
      `/chats: «${top.text}» starts at ${Math.round(top.top)}px, under the ${clearance}px inset`,
    );
  } else ok(`/chats: top clears ${clearance}px`);

  const seen = await page.evaluate(measureScreen);
  const bottom = visibleBottom(profile);

  if (seen.docWidth > seen.innerWidth || seen.scrollerWidth > 1) {
    fail(
      profile,
      `/chats: wider than the screen (${seen.docWidth}px in ${seen.innerWidth}px)`,
    );
  } else ok('/chats: no sideways scroll');

  if (!seen.bar) {
    fail(profile, '/chats: no tab bar');
  } else if (Math.abs(seen.bar.bottom - bottom) > TOLERANCE) {
    fail(
      profile,
      `/chats: tab bar ends at ${Math.round(seen.bar.bottom)}px, the visible bottom is ${bottom}px`,
    );
  } else ok(`/chats: tab bar flush on the visible bottom (${bottom}px)`);

  if (seen.bar && seen.lowest) {
    const under = seen.lowest.bottom - Math.min(seen.bar.top, bottom);
    if (under > TOLERANCE) {
      fail(
        profile,
        `/chats: scrolled to the end, «${seen.lowest.text}» is ${Math.round(under)}px under the tab bar`,
      );
    } else ok('/chats: last row clears the tab bar');
  }

  // A chat's preview: the sheet has to be on the screen.
  await page.getByText(LAST_CHAT).click();
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

/**
 * Android's keyboard: the webview shrinks and Telegram reports the new height.
 * The search field being typed into has to stay on the screen.
 */
async function checkKeyboard(browser, base, profile) {
  const { page, context } = await open(browser, base, profile, '/chats');
  await page
    .getByText(LAST_CHAT)
    .waitFor({ timeout: 10_000 })
    .catch(() => {});
  const field = page.locator('input').first();
  if (!(await field.count())) {
    fail(profile, 'keyboard: /chats has no field to type into');
    await context.close();
    return;
  }
  await field.focus();
  const keyboard = Math.round(profile.height * 0.42);
  await page.setViewportSize({ width: profile.width, height: profile.height - keyboard });
  await page.evaluate((h) => window.__telegram.move(h, true), profile.tg - keyboard);
  await page.waitForTimeout(400);
  const box = await field.boundingBox();
  const bottom = visibleBottom(profile, profile.tg - keyboard, profile.height - keyboard);
  if (!box || box.y < 0 || box.y + box.height > bottom + TOLERANCE) {
    fail(
      profile,
      `keyboard: the search field is at ${Math.round(box?.y ?? -1)}px, visible ends at ${bottom}px`,
    );
  } else ok('keyboard: the field being typed into stays visible');
  await context.close();
}

const { base, stop } = await serve();
const browser = await chromium.launch();
try {
  for (const profile of PROFILES) {
    console.log(
      `\n${profile.name} (${profile.width}×${profile.height}, Telegram ${profile.tg}px)`,
    );
    await checkList(browser, base, profile);
    if (profile.platform === 'android') {
      await checkRestore(browser, base, profile);
      await checkKeyboard(browser, base, profile);
    }
  }
} finally {
  await browser.close();
  stop();
}

if (failures.length) {
  console.error(`\n${failures.length} layout failure(s):\n  ${failures.join('\n  ')}`);
  process.exit(1);
}
console.log('\nEvery profile lays out inside what Telegram shows.');
