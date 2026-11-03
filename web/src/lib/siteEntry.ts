/**
 * How the app sends a browser, which it cannot serve, on to the public site.
 *
 * Not to the site's bare root: konnekt.cz/ once answered a permanent redirect
 * to the app, browsers that saw it keep it, and sent back there they would go
 * round between the two hosts for ever. An address that redirect was never
 * cached for breaks that loop; the landing's canonical stays the clean root.
 * Any other redirect a browser may keep is met by leaving once per tab: a
 * browser back again is shown a link instead.
 */

const LEFT = 'konnekt.leftForSite';

export function siteEntry(site: string): string {
  return `${site.replace(/\/+$/, '')}/?from=app`;
}

/** Where to send the browser now, or null when it has been sent once already. */
export function siteRedirect(
  site: string,
  session: () => Pick<Storage, 'getItem' | 'setItem'>,
): string | null {
  try {
    const tab = session();
    if (tab.getItem(LEFT)) return null;
    tab.setItem(LEFT, '1');
  } catch {
    // No storage to remember in: the address alone breaks the loop we know of.
  }
  return siteEntry(site);
}
