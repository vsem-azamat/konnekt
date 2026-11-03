/**
 * What every catalog page does with its response: how long it may be kept,
 * and what it answers when it has nothing to show.
 */

import { DEFAULT_LANG, LANGS, type Lang } from '../paths.ts';
import { CATALOG_TEXTS } from './texts.ts';

/**
 * Cloudflare keeps a page ten minutes, by the Cache Rule that makes it cache
 * these paths' HTML at all (set with the deploy that brings them), and for a
 * day past that serves the last one while it asks again or while the server
 * answers an error; a browser asks every time. A new chat is on the site
 * within ten minutes, and nobody has to purge anything.
 */
export const CACHED =
  'public, max-age=0, s-maxage=600, stale-while-revalidate=86400, stale-if-error=86400';
/** A page that is not there, such as a university with no chats: kept a minute. */
const MISSING = 'public, max-age=0, s-maxage=60';

/** The page's language from its prefix: none is Russian, an unknown one is no page. */
export function langOf(prefix: string | undefined): Lang | null {
  if (prefix === undefined) return DEFAULT_LANG;
  const lang = LANGS.find((l) => l === prefix);
  return lang && lang !== DEFAULT_LANG ? lang : null;
}

export function notFound(): Response {
  return new Response('Not found', {
    status: 404,
    headers: { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': MISSING },
  });
}

/**
 * The APIs failed with nothing kept to fall back on. Not cached: Cloudflare
 * keeps serving the last good page meanwhile (stale-if-error).
 */
export function unavailable(lang: Lang): Response {
  return new Response(CATALOG_TEXTS[lang].unavailable, {
    status: 503,
    headers: {
      'Content-Type': 'text/plain; charset=utf-8',
      'Cache-Control': 'no-store',
      'Retry-After': '60',
    },
  });
}

/** Where the app lives (the deploy's WEBAPI_PUBLIC_URL), as the layout reads it. */
export function appOrigin(): string {
  return (process.env.APP_URL || 'https://localhost:5173').replace(/\/+$/, '');
}

/** One of the landing's six tones for a name: the same wherever it shows. */
export function toneOf(name: string): number {
  return [...name].reduce((sum, c) => sum + (c.codePointAt(0) ?? 0), 0) % 6;
}
