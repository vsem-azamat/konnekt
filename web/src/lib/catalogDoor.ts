/**
 * Where a call to the catalog goes, and with what (#293).
 *
 * Inside Telegram the app asks the catalog itself, signed with initData. The
 * console opened in a browser has none: it asks webapi under its session
 * cookie, and webapi asks the catalog for the super admin it signed in, in the
 * language the console names. webapi serves only the console's screens that
 * way, which are the only ones a browser opens.
 *
 * Kept apart from api.ts, which needs the Telegram SDK and Vite, so a test can
 * import it.
 */

export type CatalogDoor = 'init-data' | 'console-session';

/**
 * webapi said the console's session is gone while asking for the catalog. The
 * console answers it by signing in again, as it does for its own calls
 * (console/browser.ts, `endsSession`).
 */
export class CatalogSessionEnded extends Error {
  constructor() {
    super('the console session behind a catalog call has ended');
    this.name = 'CatalogSessionEnded';
  }
}

const CONSOLE_LANGS = new Set(['ru', 'cs', 'en', 'uk']);

/** `search` is `''` or a query string with its `?`, as api.ts builds it. */
export function catalogCall(
  door: CatalogDoor,
  path: string,
  search: string,
  lang?: string,
): { url: string; initData: boolean } {
  if (door === 'init-data') return { url: `/api/v1${path}${search}`, initData: true };
  const params = new URLSearchParams(search);
  if (lang && CONSOLE_LANGS.has(lang)) params.set('lang', lang);
  const query = params.toString();
  return { url: `/api/catalog${path}${query ? `?${query}` : ''}`, initData: false };
}
