/*
 * What the browser checks need before they can measure anything.
 *
 * Both of them drive the real app in a real browser, so both need the same
 * three things to be true — the dev server answering, the API behind it, and
 * init data it accepts — and both need the same phones. Kept here because two
 * copies of a precondition drift, and the copy that drifts is the one that
 * stops noticing: a check that measures an error state reports on the error
 * state's height, cleanly and meaninglessly.
 */

export const BASE = process.env.BASE || 'https://localhost:5173';

/** Real phones. The short ones are where the last few pixels appear. */
export const VIEWPORTS = [
  { width: 390, height: 664 },
  { width: 360, height: 640 },
  { width: 390, height: 568 },
];

/**
 * A context that renders like a phone rather than like this machine.
 *
 * `deviceScaleFactor` and the touch flags are not decoration: they decide
 * which media features match, and with them how much of the layout is the one
 * a person actually gets. `ignoreHTTPSErrors` because mkcert's certificate is
 * not in this process's trust store, and a TLS error would otherwise look
 * exactly like whatever the check was about to conclude.
 */
export function phoneContext(browser, viewport) {
  return browser.newContext({
    viewport,
    deviceScaleFactor: 2,
    isMobile: true,
    hasTouch: true,
    ignoreHTTPSErrors: true,
  });
}

/**
 * Stop before measuring anything if the thing being measured is not there.
 *
 * Exits the process rather than throwing: every caller's answer to "the stack
 * is not up" is the same, and it is not a finding about the app.
 *
 * Checked in the phone context and not a plain desktop one, which is a change
 * from where this came from: the point of a precondition is that the thing it
 * clears is the thing that then gets measured, and both callers measure a
 * phone.
 */
export async function preflight(browser) {
  const context = await phoneContext(browser, VIEWPORTS[0]);
  const page = await context.newPage();
  const fail = async (why, hint) => {
    console.error(`Cannot measure against ${BASE}: ${why}`);
    console.error(hint);
    await browser.close();
    process.exit(2);
  };

  try {
    const health = await page.goto(`${BASE}/healthz`, { timeout: 15000 });
    if (!health?.ok()) throw new Error(`/healthz answered ${health?.status()}`);
    const body = await page.evaluate(() => document.body.textContent ?? '');
    if (!body.includes('"database":"ok"')) {
      throw new Error(`/healthz says ${body.trim().slice(0, 120)}`);
    }
  } catch (error) {
    await fail(
      error.message,
      'Start the dev server (pnpm dev) with the catalog API behind it first.',
    );
  }

  // The home screen's category grid only exists once an authenticated request
  // has come back. Without it every data screen renders an error state, which
  // has a height of its own and would be measured as if it were the screen.
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  const gotData = await page.evaluate(() =>
    Boolean(document.querySelector('[class*="grid"]')),
  );
  if (!gotData) {
    await fail(
      'the home screen came up without its categories',
      'The API is rejecting this init data. Put a signed VITE_MOCK_INIT_DATA in web/.env.local.',
    );
  }
  await context.close();
}
