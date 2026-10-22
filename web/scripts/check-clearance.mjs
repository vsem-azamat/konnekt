/*
 * The end of every list can be reached, and it stops above the tab bar.
 *
 * Measured against the height Telegram reports, not only against the window,
 * because the two are not the same number on a phone. Telegram for Android
 * reports the sheet's whole swipe container while the webview sits below its
 * action bar (`BotWebViewContainer.invalidateViewPortHeight`), so an expanded
 * app is told it is about a header taller than the window it is drawn in.
 * The app box took Telegram's number, ran past the bottom of the window, and
 * the last row and a half of «Чаты» could not be scrolled to: they were under
 * the bottom edge, and the row above them under the tab bar (October 2026,
 * Pixel). Telegram for iOS errs the other way and reports less than the
 * webview while its bottom button is up.
 *
 * So each screen is measured with Telegram's height equal to the window,
 * taller than it and shorter than it, and with a gesture bar's inset. The
 * mock in `src/mockEnv.ts` is a desktop client, where the SDK derives the
 * height from the window and the two always agree, which is why nothing else
 * here could see this. The reported height is imposed as `--app-height`, the
 * variable the app publishes it in.
 *
 * Needs only the dev server: the API is answered here, with a directory long
 * enough to scroll, so the screens measured are the full ones and not their
 * error states. Run `pnpm dev` (or with VITE_NO_HTTPS=1 and
 * BASE=http://localhost:5173) and then `pnpm check:clearance`.
 */

import { chromium } from 'playwright';

import { BASE, phoneContext, VIEWPORTS } from './lib/stack.mjs';

/** Telegram's height minus the window's: agreeing, Android's, iOS's. */
const DISAGREEMENTS = [0, 100, -60];

/** A gesture bar, as Android reports it. */
const INSET = 24;

/** The directory and a section of it, both under the tab bar. */
const ROUTES = ['/chats', '/chats/Section'];

/** Sub-pixel layout leaves fractions behind. */
const ROUNDING = 1;

function directory() {
  const chat = (n, extra) => ({
    title: `Chat ${n}`,
    link: `https://t.me/check_clearance_${n}`,
    group: null,
    institution: null,
    activity: 'quiet',
    member_count: 100 + n,
    is_forum: false,
    external: false,
    avatar: null,
    ...extra,
  });
  return [
    ...Array.from({ length: 14 }, (_, n) => chat(n, { group: 'Section' })),
    ...Array.from({ length: 14 }, (_, n) => chat(100 + n)),
  ];
}

async function answerApi(page) {
  const chats = JSON.stringify(directory());
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/public/catalog') {
      return route.fulfill({ contentType: 'application/json', body: chats });
    }
    if (path.endsWith('/me')) return route.fulfill({ status: 404, body: '{}' });
    if (path.endsWith('/client-errors')) return route.fulfill({ status: 204 });
    return route.fulfill({ contentType: 'application/json', body: '[]' });
  });
}

/**
 * Where the end of the list lands once scrolled as far as it goes.
 *
 * Runs in the browser. The visible area is the smaller of the two heights:
 * nothing paints outside the window, and Telegram covers whatever lies below
 * its own number.
 */
function look(reported) {
  const root = document.getElementById('root');
  root.scrollTop = root.scrollHeight;
  const rows = [...root.querySelectorAll('button')].filter(
    (el) => !el.closest('nav') && el.getBoundingClientRect().height > 0,
  );
  const tabs = document.querySelector('nav');
  return {
    rows: rows.length,
    travel: root.scrollHeight - root.clientHeight,
    lastBottom: rows.at(-1)?.getBoundingClientRect().bottom ?? Number.NaN,
    tabsTop: tabs?.getBoundingClientRect().top ?? Number.NaN,
    tabsBottom: tabs?.getBoundingClientRect().bottom ?? Number.NaN,
    visible: Math.min(reported, window.innerHeight),
  };
}

const browser = await chromium.launch();
const failures = [];

for (const viewport of VIEWPORTS) {
  const context = await phoneContext(browser, viewport);
  for (const delta of DISAGREEMENTS) {
    const reported = viewport.height + delta;
    const label = `${viewport.width}x${viewport.height}, Telegram ${reported}px`;
    console.log(`\n${label}`);
    for (const path of ROUTES) {
      const page = await context.newPage();
      await answerApi(page);
      try {
        await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' });
      } catch (error) {
        console.error(`\nCannot reach ${BASE}${path}: ${error.message}`);
        await browser.close();
        process.exit(2);
      }
      // Imposed over what the app publishes: a stylesheet's !important wins
      // over the inline value set on <html>.
      await page.addStyleTag({
        content:
          `:root{--app-height:${reported}px !important;` +
          `--tg-viewport-safe-area-inset-bottom:${INSET}px !important}` +
          '#eruda{display:none !important}',
      });
      // The list, not merely the page: measured before the rows arrive, a
      // screen of nothing fits anywhere and reports nothing.
      await page
        .waitForFunction(
          () => document.querySelectorAll('#root button:not(nav button)').length >= 10,
          null,
          { timeout: 5000 },
        )
        .catch(() => {});
      await page.waitForTimeout(300);
      const seen = await page.evaluate(look, reported);

      const problems = [];
      if (seen.rows < 10 || seen.travel <= 0) {
        problems.push(
          `only ${seen.rows} rows and ${seen.travel}px of travel: not the full list`,
        );
      }
      if (seen.lastBottom > seen.tabsTop + ROUNDING) {
        problems.push(
          `last row ends at ${seen.lastBottom}, under the tab bar at ${seen.tabsTop}`,
        );
      }
      if (seen.tabsBottom > seen.visible + ROUNDING) {
        problems.push(
          `tab bar ends at ${seen.tabsBottom}, below the visible ${seen.visible}`,
        );
      }
      console.log(
        `  ${problems.length ? 'FAIL' : 'ok  '} ${path.padEnd(16)}` +
          ` last row ${Math.round(seen.lastBottom)}  bar ${Math.round(seen.tabsTop)}` +
          `–${Math.round(seen.tabsBottom)}  visible ${seen.visible}`,
      );
      for (const problem of problems) failures.push(`${path} at ${label}: ${problem}`);
      await page.close();
    }
  }
  await context.close();
}

await browser.close();

if (failures.length) {
  console.error(
    `\n${failures.length} case(s) hide the end of the list:\n  ${failures.join('\n  ')}`,
  );
  process.exit(1);
}
console.log('\nThe end of every list is reachable and clear of the tab bar.');
