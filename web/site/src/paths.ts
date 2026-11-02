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
 * Where the landing sends someone who opened it inside Telegram, or null.
 *
 * Telegram opens the Mini App at /chats and the like, never at the root, but a
 * button in an old message may still name the root. Telegram puts the launch
 * data in the fragment, and that is the one sign used: the app sends a
 * browser back here without it, so the two pages cannot bounce off each other.
 */
export function telegramHome(hash: string, search: string): string | null {
  return hash.includes('tgWebAppData') ? `/home${search}${hash}` : null;
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
