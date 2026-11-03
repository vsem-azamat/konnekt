/**
 * How the app sends a browser, which it cannot serve, on to the public site.
 *
 * Not to the site's bare root: konnekt.cz/ once answered a permanent redirect
 * to the app, browsers that saw it keep it, and sent back there they would go
 * round between the two hosts for ever. An address that redirect was never
 * cached for breaks that loop; the landing's canonical stays the clean root.
 * Any other redirect a browser may keep is met by not leaving twice in a few
 * seconds from one tab: a loop is back within milliseconds and is shown a link
 * instead, while a person clicking the site's home link through a redirect
 * their browser still keeps is sent on as before.
 */

const LEFT = 'konnekt.leftForSite';
/** How soon a browser back again counts as a loop rather than a click. */
const LOOP_WINDOW_MS = 10_000;

export function siteEntry(site: string): string {
  return `${site.replace(/\/+$/, '')}/?from=app`;
}

/** Where to send the browser now, or null when it was sent there moments ago. */
export function siteRedirect(
  site: string,
  session: () => Pick<Storage, 'getItem' | 'setItem'>,
  now: number,
): string | null {
  try {
    const tab = session();
    const left = Number(tab.getItem(LEFT));
    if (left && now - left < LOOP_WINDOW_MS) return null;
    tab.setItem(LEFT, String(now));
  } catch {
    // No storage to remember in: the address alone breaks the loop we know of.
  }
  return siteEntry(site);
}
