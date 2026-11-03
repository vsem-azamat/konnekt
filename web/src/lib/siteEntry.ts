/**
 * How the app sends a browser, which it cannot serve, on to the public site.
 *
 * Not to the site's bare root: konnekt.cz/ once answered a permanent redirect
 * to the app, browsers that saw it keep it, and sent back there they would go
 * round between the two hosts for ever. An address that redirect was never
 * cached for breaks that loop; the landing's canonical stays the clean root.
 * Any other redirect a browser may keep is met by not leaving a third time in
 * a few seconds from one tab: a loop is back within milliseconds, again and
 * again, and is shown where the app opens instead (pages/OpenInTelegram.tsx),
 * while a person opening the address again, or clicking the site's home link
 * through a redirect their browser still keeps, is sent on as before.
 */

const LEFT = 'konnekt.leftForSite';
/** How soon a third return counts as a loop rather than a person. */
const LOOP_WINDOW_MS = 10_000;

export function siteEntry(site: string): string {
  return `${site.replace(/\/+$/, '')}/?from=app`;
}

/** Where to send the browser now, or null when it was sent there twice moments ago. */
export function siteRedirect(
  site: string,
  session: () => Pick<Storage, 'getItem' | 'setItem'>,
  now: number,
): string | null {
  try {
    const tab = session();
    // The last two times this tab was sent on, oldest first.
    const times = (tab.getItem(LEFT) ?? '').split(',').map(Number).filter(Boolean);
    // A gap below zero is a clock set back, not a loop.
    const gap = now - (times[0] ?? 0);
    if (times.length === 2 && gap >= 0 && gap < LOOP_WINDOW_MS) return null;
    tab.setItem(LEFT, [...times.slice(-1), now].join(','));
  } catch {
    // No storage to remember in: the address alone breaks the loop we know of.
  }
  return siteEntry(site);
}

/**
 * The way into the bot: the site's own, which redirects to the bot from the
 * token the catalog runs with, so no bot's name is written here.
 */
export function botEntry(site: string): string {
  return `${site.replace(/\/+$/, '')}/api/v1/open?app=1`;
}
