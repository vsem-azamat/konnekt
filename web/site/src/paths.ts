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

/** The language of an article from its content id, `<lang>/<slug>`. */
export function langOf(id: string): Lang {
  const lang = id.split('/')[0];
  if (!LANGS.includes(lang as Lang)) throw new Error(`article ${id} is in no language`);
  return lang as Lang;
}

export function slugOf(id: string): string {
  return id.slice(id.indexOf('/') + 1);
}

export function articlePath(id: string): string {
  return localePath(langOf(id), `/articles/${slugOf(id)}/`);
}

/** One language's version of a page, at its full path (prefix included). */
export interface Version {
  lang: Lang;
  path: string;
}

/** The versions of a page that has the same path, `path` in Russian, in each of `langs`. */
export function versionsOf(path: string, langs: readonly Lang[]): Version[] {
  return LANGS.filter((lang) => langs.includes(lang)).map((lang) => ({
    lang,
    path: localePath(lang, path),
  }));
}

export interface Alternate {
  hreflang: string;
  href: string;
}

/** The `hreflang` links of a page's versions, with Russian as the default. */
export function alternates(versions: readonly Version[], site: string): Alternate[] {
  const origin = site.replace(/\/+$/, '');
  const links = LANGS.flatMap((lang) =>
    versions
      .filter((version) => version.lang === lang)
      .map(({ path }) => ({ hreflang: lang, href: `${origin}${path}` })),
  );
  const russian = links.find((link) => link.hreflang === DEFAULT_LANG);
  return russian ? [...links, { hreflang: 'x-default', href: russian.href }] : links;
}

/**
 * The versions of a page whose search engines may keep: a noindex
 * translation (an example, an empty list) prints no hreflang of its own, so
 * naming it would be a link it never returns.
 */
export function indexed(
  versions: readonly Version[],
  hidden: readonly string[],
): Version[] {
  return versions.filter((version) => !hidden.includes(version.path));
}

/**
 * Where the site sends a Telegram launch that landed on it, or null.
 *
 * The app has its own host (`app`), but buttons already sent in Telegram name
 * this one, and the catalog's notifications named its bare root. Telegram puts
 * the launch data in the fragment, which the server never sees, so the page
 * itself sends it on: to the app's first screen, fragment and all, or from
 * the public catalogue (`path`, /chats/ in any language) to the app's chats,
 * which those buttons named while the address was the app's. A browser
 * without it stays.
 */
export function telegramHome(
  hash: string,
  search: string,
  app: string,
  path = '/',
): string | null {
  const screen = /^(\/[a-z]{2})?\/chats\/?$/.test(path) ? '/chats' : '/home';
  return hash.includes('tgWebAppData')
    ? `${app.replace(/\/+$/, '')}${screen}${search}${hash}`
    : null;
}

export interface ArticleEntry {
  id: string;
  draft: boolean;
  /** The same in every translation of one article; each has a slug in its own language. */
  translationKey: string;
  /** Who wrote it and who checked it, by their ids in the authors collection. */
  people?: readonly string[];
}

/** The sections an article belongs to, one each; their names are in texts.ts. */
export const RUBRICS = ['admission', 'visa', 'housing', 'study', 'work'] as const;
export type Rubric = (typeof RUBRICS)[number];

export function authorPath(lang: Lang, id: string): string {
  return localePath(lang, `/authors/${id}/`);
}

/**
 * The authors' pages: one for each person in each language they wrote or
 * checked an article in, `hidden` while every one of those is an example.
 */
export function authorPages(
  articles: readonly ArticleEntry[],
): { id: string; lang: Lang; hidden: boolean }[] {
  const pages = new Map<string, { id: string; lang: Lang; hidden: boolean }>();
  for (const article of articles) {
    const lang = langOf(article.id);
    for (const id of article.people ?? []) {
      const key = authorPath(lang, id);
      const page = pages.get(key) ?? { id, lang, hidden: true };
      page.hidden &&= article.draft;
      pages.set(key, page);
    }
  }
  return [...pages.values()];
}

/** Slugs the section's own pages take: an article by one of these names would hide them. */
export const RESERVED_SLUGS = ['topics', 'tags'];

/**
 * Refuses what would break an address or a translation: an article under a
 * reserved slug, or two articles in one language sharing a translation key
 * (which of them would the others name?).
 */
export function checkArticles(articles: readonly ArticleEntry[]): void {
  const seen = new Map<string, string>();
  for (const { id, translationKey } of articles) {
    if (RESERVED_SLUGS.includes(slugOf(id))) {
      throw new Error(`article ${id}: the slug ${slugOf(id)} is the section's own`);
    }
    const key = `${langOf(id)}/${translationKey}`;
    const other = seen.get(key);
    if (other) {
      throw new Error(
        `articles ${other} and ${id} are both the ${langOf(id)} ${translationKey}`,
      );
    }
    seen.set(key, id);
  }
}

/** Every language's version of `article`, itself included, by its translation key. */
export function translationsOf(
  article: ArticleEntry,
  articles: readonly ArticleEntry[],
): Version[] {
  return articles
    .filter((other) => other.translationKey === article.translationKey)
    .map((other) => ({ lang: langOf(other.id), path: articlePath(other.id) }));
}

/**
 * Pages that carry `noindex`: every example article, the list of articles in
 * every language that has no published one yet, and an author's page with
 * nothing but examples on it. The sitemap leaves them out.
 */
export function hiddenPaths(articles: readonly ArticleEntry[]): string[] {
  const published = new Set(articles.filter((a) => !a.draft).map((a) => langOf(a.id)));
  const drafts = articles.filter((a) => a.draft).map((a) => articlePath(a.id));
  const emptyLists = LANGS.filter((lang) => !published.has(lang)).map((lang) =>
    localePath(lang, '/articles/'),
  );
  const authors = authorPages(articles)
    .filter((page) => page.hidden)
    .map((page) => authorPath(page.lang, page.id));
  return [...drafts, ...emptyLists, ...authors];
}
