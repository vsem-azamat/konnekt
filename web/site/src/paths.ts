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

import { parse } from 'yaml';

export const LANGS = ['ru', 'uk', 'cs', 'en'] as const;
export type Lang = (typeof LANGS)[number];
export const DEFAULT_LANG: Lang = 'ru';

/** `path` (from the root, with its trailing slash) in `lang`. */
export function localePath(lang: Lang, path: string): string {
  return lang === DEFAULT_LANG ? path : `/${lang}${path}`;
}

/**
 * The menu item a page belongs to, by its path (with or without its
 * language's prefix): the articles for an article, a rubric, a tag or an
 * author; the chats for the catalogue of chats and of universities. The
 * landing's own sections are anchors, marked as they are scrolled to.
 */
export function navSection(path: string): 'articles' | 'chats' | null {
  const own = path.replace(/^\/(?:uk|cs|en)(?=\/)/, '');
  if (/^\/(?:articles|authors)\//.test(own)) return 'articles';
  if (/^\/(?:chats|universities)\//.test(own)) return 'chats';
  return null;
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
  rubric?: string;
  tags?: readonly string[];
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

/** A slug, a translation key, a tag: lowercase latin words joined by hyphens. */
export const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** The published articles in `lang`, newest first: the landing's and the menu's. */
export function newestPublished<
  T extends { id: string; draft: boolean; published: Date },
>(articles: readonly T[], lang: Lang): T[] {
  return articles
    .filter((article) => !article.draft && langOf(article.id) === lang)
    .sort((a, b) => b.published.valueOf() - a.published.valueOf());
}

/** Slugs the section's own pages take: an article by one of these names would hide them. */
export const RESERVED_SLUGS = ['topics', 'tags'];

/**
 * Refuses what would break an address or a translation: a file name that is
 * not already a slug (Astro would rewrite it into one, and the config, which
 * reads file names, would then name a page that does not exist), an article
 * under a reserved slug, two articles in one language sharing a translation
 * key (which of them would the others name?), or a tag `tags` does not list
 * (Astro only logs an unknown reference, and would build its page).
 */
export function checkArticles(
  articles: readonly ArticleEntry[],
  tags?: readonly string[],
): void {
  const seen = new Map<string, string>();
  for (const { id, translationKey, tags: carried = [] } of articles) {
    const unknown = tags ? carried.filter((tag) => !tags.includes(tag)) : [];
    if (unknown.length > 0) {
      throw new Error(`article ${id}: no tag ${unknown.join(', ')} in content/tags.yaml`);
    }
    if (!SLUG.test(slugOf(id))) {
      throw new Error(
        `article ${id}: the file name is not a slug (lowercase latin, hyphens)`,
      );
    }
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

/** A tag's page is kept out of search until this many published articles carry it: a thinner one is a thin page. */
export const TAG_MIN = 3;

export interface Listing {
  kind: 'topics' | 'tags';
  key: string;
  lang: Lang;
  path: string;
  /** The published articles on it. */
  count: number;
  hidden: boolean;
}

/**
 * The pages that list articles by rubric (`/articles/topics/<rubric>/`) and
 * by tag (`/articles/tags/<tag>/`), in each language that has an article on
 * them. A rubric's is hidden while it lists only examples; a tag's until
 * TAG_MIN published articles carry it.
 */
export function listings(articles: readonly ArticleEntry[]): Listing[] {
  const pages = new Map<string, Listing>();
  const add = (kind: Listing['kind'], key: string, lang: Lang, draft: boolean) => {
    const path = localePath(lang, `/articles/${kind}/${key}/`);
    const page = pages.get(path) ?? { kind, key, lang, path, count: 0, hidden: true };
    if (!draft) page.count += 1;
    page.hidden = page.count < (kind === 'tags' ? TAG_MIN : 1);
    pages.set(path, page);
  };
  for (const article of articles) {
    const lang = langOf(article.id);
    if (article.rubric) add('topics', article.rubric, lang, article.draft);
    for (const tag of article.tags ?? []) add('tags', tag, lang, article.draft);
  }
  const all = [...pages.values()];
  return [
    ...all.filter((p) => p.kind === 'topics'),
    ...all.filter((p) => p.kind === 'tags'),
  ];
}

/**
 * What to read next after `article`: published articles in its language,
 * those of its rubric first, then by how many tags they share with it.
 */
export function related<T extends ArticleEntry>(
  article: ArticleEntry,
  articles: readonly T[],
  limit: number,
): T[] {
  const lang = langOf(article.id);
  const tags = new Set(article.tags ?? []);
  const score = (other: ArticleEntry) =>
    (other.rubric === article.rubric ? tags.size + 1 : 0) +
    (other.tags ?? []).filter((tag) => tags.has(tag)).length;
  return articles
    .filter(
      (other) => other.id !== article.id && !other.draft && langOf(other.id) === lang,
    )
    .map((other) => ({ other, score: score(other) }))
    .filter(({ score }) => score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, limit)
    .map(({ other }) => other);
}

/**
 * A file's frontmatter, read as Astro reads it (a leading BOM allowed, any
 * line ending). A file without it is refused rather than read as empty: the
 * config would take it for a published article Astro may see as a draft.
 */
export function readFrontmatter(text: string, file: string): Record<string, unknown> {
  const found = text
    .replace(/^\uFEFF/, '')
    .match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!found) throw new Error(`${file}: no frontmatter`);
  return parse(found[1] ?? '') ?? {};
}

/**
 * An article's hreflang links in the sitemap, by its translation key, as its
 * page names them; undefined for any other page, which the sitemap pairs by
 * path itself. Pairing an article by path would name as translations two
 * articles that only share a slug, and miss real ones with slugs of their own.
 */
export function sitemapLinks(
  path: string,
  articles: readonly ArticleEntry[],
  hidden: readonly string[],
  site: string,
): { lang: string; url: string }[] | undefined {
  const article = articles.find((one) => articlePath(one.id) === path);
  if (!article) return undefined;
  return alternates(indexed(translationsOf(article, articles), hidden), site).map(
    ({ hreflang, href }) => ({ lang: hreflang, url: href }),
  );
}

/**
 * Pages that carry `noindex`: every example article, the list of articles in
 * every language that has no published one yet, an author's page with
 * nothing but examples on it, and the listings `listings` hides. The sitemap
 * leaves them out.
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
  const lists = listings(articles)
    .filter((page) => page.hidden)
    .map((page) => page.path);
  return [...drafts, ...emptyLists, ...authors, ...lists];
}
