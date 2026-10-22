/*
 * Nothing should be scrollable to a stretch of nothing.
 *
 * The contract is in catalog/docs/architecture.md: the Mini App is a screen, not a
 * document. The bug this guards against is not "the page scrolls" — a list is
 * supposed to — it is travel that reveals nothing, which reads as a broken
 * screen and is invisible on a desktop window.
 *
 * "A screen that fits must not scroll" was the obvious rule and it is the
 * wrong one. For any layout there is a band of viewport heights where the
 * content is a handful of pixels too tall, so a threshold on travel only moves
 * the failing size around; it says nothing about whether the travel was
 * pointless. What separates the bug from an ordinary short list is what is
 * waiting at the end of the scroll.
 *
 * So the measurement is geometric and needs no scrolling at all: how far is
 * the lowest thing that paints from the bottom of the screen's content box?
 * The screen's own `padding-bottom` is by design and is subtracted, which is
 * also what keeps the number honest on a phone with a home indicator, where
 * that padding includes the inset. Anything left over is dead space.
 *
 * A container does not paint on behalf of its children: a spacer nested inside
 * a card list is the same bug as one at the foot of the screen, and an earlier
 * version of this check — which took any element with children as content —
 * could see the second and not the first.
 *
 * Measured at several viewport sizes, because a screen that fits on a tall
 * phone is not the question.
 *
 * What it cannot do: the mock in `src/mockEnv.ts` reports `tdesktop`, where the
 * SDK synthesises the viewport from `window.innerHeight`, so `--app-height`
 * here is always the same number as the `100dvh` fallback. The iOS and Android
 * path that variable exists for is not exercised here; check-clearance.mjs
 * imposes the heights those clients report instead.
 *
 * Needs the dev server (`pnpm dev`) and the API behind it, with a signed
 * `VITE_MOCK_INIT_DATA` in `web/.env.local` — the API answers 401 to the
 * unsigned mock, and a screen full of error states is not the screen being
 * measured. All three are checked before anything is measured.
 *
 * `pnpm dev` serves https through mkcert, which needs sudo once. Where it
 * cannot have it, run the server with VITE_NO_HTTPS=1 and pass
 * BASE=http://localhost:5173.
 */

import { chromium } from 'playwright';

import { BASE, phoneContext, preflight, VIEWPORTS } from './lib/stack.mjs';

/**
 * The detail screens are behind an id this script cannot know, so they are
 * reached the way a person reaches them: by tapping the first row of the list
 * that leads there.
 *
 * One screen cannot be reached that way at all. `/offer/prices` opens on
 * Telegram's main button, which no browser has, and it redirects to `/offer`
 * without a choice in router state — so it is entered by pushing that state,
 * the same shape the app pushes. Until it was, the screen was not measured at
 * any size; being measured is the whole of what this buys. What it catches is
 * what it catches everywhere else: emptiness under the last thing on the
 * screen. A gap left between two cards is above the segmented control at the
 * foot, and no version of this check has ever seen one.
 *
 * `expect` and `expectCount` are what stop a rename of a service code from
 * quietly measuring something else under this screen's name. Counted, not
 * merely present: one code renamed still draws the other's card, and a screen
 * that has lost half of what it was chosen to show measures as fine.
 */
const ROUTES = [
  { path: '/' },
  { path: '/ask' },
  { path: '/results', into: { name: 'helper detail', click: 'button[class*="card"]' } },
  { path: '/mine', into: { name: 'request detail', click: 'button[class*="card"]' } },
  { path: '/life' },
  { path: '/chats' },
  { path: '/ads' },
  { path: '/ads/chats' },
  { path: '/ads/app' },
  { path: '/join' },
  { path: '/profile' },
  {
    path: '/offer',
    into: {
      name: '/offer/prices',
      // Where to push it. `name` is a label — the click routes call themselves
      // "helper detail" — and a label is not a URL.
      path: '/offer/prices',
      // One card of each form shape, so every question this screen can ask is
      // on the screen being measured: a lesson takes subjects, an errand takes
      // a checklist, and a written work takes a turnaround.
      state: { picked: ['tutoring', 'insurance', 'writing'] },
      expect: '[class*="svcCard"]',
      expectCount: 3,
    },
  },
  { path: '/my-helper' },
  { path: '/nope' },
];

/**
 * Sub-pixel layout leaves fractions behind; a spacer never weighs four.
 *
 * Everything a screen keeps clear on purpose is already subtracted — it is
 * `.screen`'s own `padding-bottom` in ui.module.css, home indicator included —
 * so this is a tolerance and not an allowance.
 */
const ROUNDING = 4;

const browser = await chromium.launch();
const failures = [];
/** Screens that never came up — a broken check, not a thin database. */
const unreachable = [];
const skipped = new Set();

/**
 * How much emptiness the screen has under its lowest visible thing.
 *
 * Runs in the browser. Declared as a plain function so `page.evaluate` can
 * serialise it, inner helper and all.
 */
function look() {
  /**
   * Does this element put anything on the screen *itself*?
   *
   * Its children do not count for it: a container's box is only as meaningful
   * as what is inside it, and a spacer wrapped in a div is still a spacer.
   * What counts is text of its own, a box it fills or outlines, or being one
   * of the elements that draws by nature.
   */
  function paints(el) {
    // Asked first, and of the whole ancestor chain: an element with text in it
    // is still invisible under a hidden or fully transparent parent, and text
    // was the one test that used to answer before anything looked at style.
    if (
      !el.checkVisibility({
        opacityProperty: true,
        visibilityProperty: true,
        contentVisibilityAuto: true,
      })
    ) {
      return false;
    }
    if (/^(svg|img|canvas|video|input|textarea|select|hr)$/i.test(el.tagName))
      return true;
    for (const node of el.childNodes) {
      if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) return true;
    }
    for (const pseudo of ['::before', '::after']) {
      const drawn = getComputedStyle(el, pseudo);
      if (drawn.content !== 'none' && drawn.content !== 'normal') return true;
    }
    const style = getComputedStyle(el);
    if (style.backgroundImage !== 'none') return true;
    if (!['transparent', 'rgba(0, 0, 0, 0)'].includes(style.backgroundColor)) return true;
    if (style.boxShadow !== 'none') return true;
    if (Number.parseFloat(style.outlineWidth) > 0 && style.outlineStyle !== 'none') {
      return true;
    }
    return ['Top', 'Right', 'Bottom', 'Left'].some(
      (side) => Number.parseFloat(style[`border${side}Width`]) > 0,
    );
  }

  /**
   * Where this element's paint actually stops.
   *
   * `getBoundingClientRect` does not know about clipping, so a tall child of a
   * short `overflow: hidden` box reports a bottom edge nobody can see. Left
   * alone that reads as content below the floor, and one negative number is
   * enough to hide every real spacer above it.
   */
  function visibleBottom(el, screen) {
    let bottom = el.getBoundingClientRect().bottom;
    for (
      let node = el.parentElement;
      node && node !== screen;
      node = node.parentElement
    ) {
      if (getComputedStyle(node).overflowY !== 'visible') {
        bottom = Math.min(bottom, node.getBoundingClientRect().bottom);
      }
    }
    return bottom;
  }

  const doc = document.documentElement;
  const root = document.getElementById('root');
  const screen = root?.firstElementChild;
  if (!screen) return { verdict: 'nothing rendered' };

  const style = getComputedStyle(screen);
  const floor =
    screen.getBoundingClientRect().bottom - Number.parseFloat(style.paddingBottom);

  let lowest = Number.NEGATIVE_INFINITY;
  for (const el of screen.querySelectorAll('*')) {
    // A sheet is fixed to the viewport and is not part of the screen's flow.
    if (getComputedStyle(el).position === 'fixed') continue;
    const box = el.getBoundingClientRect();
    if (box.height <= 0 || box.width <= 0) continue;
    if (!paints(el)) continue;
    lowest = Math.max(lowest, visibleBottom(el, screen));
  }

  // Not "clean": unmeasurable. A page whose root is not a `<Screen>` — which
  // is how the 404 was written — has no content box to measure against, and
  // calling that zero is how a mistyped route reports as spotless. It is the
  // shape of the bug this check twice had to be rescued from, so it is loud.
  if (lowest === Number.NEGATIVE_INFINITY) {
    return { verdict: 'no screen: nothing in the page paints anything' };
  }

  return {
    verdict: 'measured',
    travel: doc.scrollHeight - doc.clientHeight + (root.scrollHeight - root.clientHeight),
    // Everything between the last visible thing and where the screen's own
    // designed clearance begins.
    dead: floor - lowest,
  };
}

async function measure(page, name, label) {
  await page.waitForTimeout(900);
  // The development console is a floating panel of its own and would otherwise
  // count as content.
  await page.addStyleTag({ content: '#eruda{display:none !important}' });
  await page.waitForTimeout(100);

  const seen = await page.evaluate(look);
  if (seen.verdict !== 'measured') {
    console.error(`\n${name} at ${label}: ${seen.verdict}.`);
    await browser.close();
    process.exit(2);
  }

  // Dead space nobody can reach is just whitespace at the foot of a page.
  const dead = seen.travel > 0 ? Math.round(seen.dead) : 0;
  const pointless = dead > ROUNDING;
  console.log(
    `  ${pointless ? 'FAIL' : 'ok  '} ${name.padEnd(20)}` +
      ` travel=${Math.round(seen.travel)}px  empty=${dead}px`,
  );
  if (pointless) failures.push(`${name} at ${label}: ${dead}px of nothing`);
}

await preflight(browser);

for (const viewport of VIEWPORTS) {
  const label = `${viewport.width}x${viewport.height}`;
  const context = await phoneContext(browser, viewport);

  console.log(`\n${label}`);
  for (const route of ROUTES) {
    const page = await context.newPage();
    try {
      const response = await page.goto(`${BASE}${route.path}`, {
        waitUntil: 'networkidle',
      });
      if (response && !response.ok()) throw new Error(`HTTP ${response.status()}`);
    } catch (error) {
      console.error(`\nCannot reach ${BASE}${route.path}: ${error.message}`);
      await browser.close();
      process.exit(2);
    }

    await measure(page, route.path, label);

    if (route.into) {
      let opened = true;
      try {
        if (route.into.state) {
          await page.evaluate(
            ([usr, path]) => {
              history.pushState({ usr, key: 'check-scroll', idx: 1 }, '', path);
              dispatchEvent(new PopStateEvent('popstate', { state: history.state }));
            },
            [route.into.state, route.into.path],
          );
          // The exact count, not merely one: half a state that still names
          // something renders half a screen, and a screen missing one of the
          // two shapes it was chosen for would otherwise measure as fine.
          await page.waitForFunction(
            ([selector, wanted]) => document.querySelectorAll(selector).length === wanted,
            [route.into.expect, route.into.expectCount],
            { timeout: 5000 },
          );
        } else {
          await page.locator(route.into.click).first().click({ timeout: 5000 });
          await page.waitForURL((url) => url.pathname !== route.path, { timeout: 5000 });
        }
      } catch {
        opened = false;
      }
      if (opened) {
        await measure(page, route.into.name, label);
      } else if (route.into.state) {
        // Not the empty-list case below: nothing about the database decides
        // whether a screen entered by state comes up, so failing to reach it
        // means this check has stopped checking. Recorded and carried on with
        // — the remaining screens and sizes are still worth measuring, and one
        // broken entry should not take the whole report down with it.
        console.log(
          `  DEAD ${route.into.name.padEnd(20)} ${route.into.expect} ×` +
            `${route.into.expectCount} never appeared`,
        );
        unreachable.push(
          `${route.into.name} at ${label}: expected ${route.into.expectCount} of` +
            ` ${route.into.expect} after pushing ${JSON.stringify(route.into.state)}`,
        );
      } else {
        // An empty list is a seeding problem rather than a layout one, so it
        // does not fail the run — but it does mean a screen went unmeasured,
        // and an unmeasured screen reported as nothing at all is how a check
        // like this quietly stops being one.
        console.log(
          `  SKIP ${route.into.name.padEnd(20)} nothing in ${route.path} to open`,
        );
        skipped.add(route.into.name);
      }
    }

    await page.close();
  }

  await context.close();
}

await browser.close();

if (unreachable.length) {
  console.error(
    `\n${unreachable.length} screen(s) never came up:\n  ${unreachable.join('\n  ')}`,
  );
  console.error(
    'A screen entered by router state fails this way when what the state names' +
      ' no longer draws what it drew — a service code renamed or withdrawn, or' +
      ' a rename of the class `expect` looks for.',
  );
}
if (failures.length) {
  console.error(
    `\n${failures.length} screen(s) scroll to nothing:\n  ${failures.join('\n  ')}`,
  );
}
if (failures.length || unreachable.length) process.exit(1);
if (skipped.size) {
  console.log(`\nNot measured, nothing to open: ${[...skipped].join(', ')}.`);
}
console.log(`Every screen measured ends on content, at all ${VIEWPORTS.length} sizes.`);
