/**
 * Where each page of the public site lives, in each language.
 *
 * Russian, the language most of the audience reads, is at the root; the others
 * are under their own prefix. One address per page: there is no /ru/, and no
 * redirect by the browser's language, which a crawler has none of and which
 * would hide every other version from it.
 *
 * Pure functions, shared by the pages, the config and the tests.
 */

export const LANGS = ['ru', 'uk', 'cs', 'en'] as const;
export type Lang = (typeof LANGS)[number];
export const DEFAULT_LANG: Lang = 'ru';

/** `path` (from the root, with its trailing slash) in `lang`. */
export function localePath(lang: Lang, path: string): string {
  return lang === DEFAULT_LANG ? path : `/${lang}${path}`;
}

/** The language of a guide from its content id, `<lang>/<slug>`. */
export function langOf(id: string): Lang {
  const lang = id.split('/')[0];
  if (!LANGS.includes(lang as Lang)) throw new Error(`guide ${id} is in no language`);
  return lang as Lang;
}

export function slugOf(id: string): string {
  return id.slice(id.indexOf('/') + 1);
}

export function guidePath(id: string): string {
  return localePath(langOf(id), `/guides/${slugOf(id)}/`);
}

export interface Alternate {
  hreflang: string;
  href: string;
}

/** The `hreflang` links of a page that exists in `langs`, with Russian as the default. */
export function alternates(
  path: string,
  langs: readonly Lang[],
  site: string,
): Alternate[] {
  const origin = site.replace(/\/+$/, '');
  const links = LANGS.filter((lang) => langs.includes(lang)).map((lang) => ({
    hreflang: lang,
    href: `${origin}${localePath(lang, path)}`,
  }));
  return langs.includes(DEFAULT_LANG)
    ? [
        ...links,
        { hreflang: 'x-default', href: `${origin}${localePath(DEFAULT_LANG, path)}` },
      ]
    : links;
}

/**
 * The languages of a page whose versions search engines may keep: a noindex
 * translation (an example, an empty list) prints no hreflang of its own, so
 * naming it would be a link it never returns.
 */
export function indexedLangs(
  path: string,
  langs: readonly Lang[],
  hidden: readonly string[],
): Lang[] {
  return langs.filter((lang) => !hidden.includes(localePath(lang, path)));
}

/**
 * Where the site sends a Telegram launch that landed on it, or null.
 *
 * The app has its own host (`app`), but buttons already sent in Telegram name
 * this one, and the catalog's notifications named its bare root. Telegram puts
 * the launch data in the fragment, which the server never sees, so the page
 * itself sends it on: to the app's first screen, fragment and all. A browser
 * without it stays.
 */
export function telegramHome(hash: string, search: string, app: string): string | null {
  return hash.includes('tgWebAppData')
    ? `${app.replace(/\/+$/, '')}/home${search}${hash}`
    : null;
}

export interface GuideEntry {
  id: string;
  draft: boolean;
}

/**
 * Pages that carry `noindex`: every example guide, and the list of guides in
 * every language that has no published one yet. The sitemap leaves them out.
 */
export function hiddenPaths(guides: readonly GuideEntry[]): string[] {
  const published = new Set(guides.filter((g) => !g.draft).map((g) => langOf(g.id)));
  const drafts = guides.filter((g) => g.draft).map((g) => guidePath(g.id));
  const emptyLists = LANGS.filter((lang) => !published.has(lang)).map((lang) =>
    localePath(lang, '/guides/'),
  );
  return [...drafts, ...emptyLists];
}
