/**
 * How the console in a browser asks for the catalog's screens (#293).
 *
 * Inside Telegram the app asks the catalog itself, signed with initData. A
 * browser has none: it asks webapi under its session cookie, and webapi asks
 * the catalog for the super admin it signed in, in the language the console
 * names. webapi serves only the console's screens that way, which are the only
 * ones a browser opens. main.tsx installs this in api.ts for the browser.
 */

const CONSOLE_LANGS = new Set(['ru', 'cs', 'en', 'uk']);

/** `search` is `''` or a query string with its `?`, as api.ts builds it. */
export function catalogThroughConsole(
  path: string,
  search: string,
  lang?: string,
): { url: string; initData: boolean } {
  const params = new URLSearchParams(search);
  if (lang && CONSOLE_LANGS.has(lang)) params.set('lang', lang);
  const query = params.toString();
  return { url: `/api/catalog${path}${query ? `?${query}` : ''}`, initData: false };
}
