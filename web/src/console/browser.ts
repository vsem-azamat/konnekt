/**
 * The console opened in a browser rather than inside Telegram.
 *
 * Telegram is the one that is signed in there (`initData`); a browser signs in
 * through webapi's OpenID Connect door and keeps the cookie. This file holds
 * what that decision needs and nothing that draws.
 */

/** What webapi's callback sends back as `?error=`; anything else is not ours to show. */
export type LoginProblem = 'failed' | 'not_admin';

export function loginProblem(search: string): LoginProblem | null {
  const error = new URLSearchParams(search).get('error');
  return error === 'failed' || error === 'not_admin' ? error : null;
}

/**
 * The addresses a browser opens the console at. The domain is not asked about:
 * a browser outside Telegram on any host gets the console here and the landing
 * page elsewhere, and the host that is meant to serve the console sends its
 * root to `/console` itself.
 */
export function isBrowserConsolePath(pathname: string): boolean {
  return (
    pathname === '/login' || pathname === '/console' || pathname.startsWith('/console/')
  );
}
