import { globSync, readFileSync } from 'node:fs';
import { satteri } from '@astrojs/markdown-satteri';
import node from '@astrojs/node';
import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';
import { parse } from 'yaml';

import { readingPlugin } from './src/articles/reading.ts';
import { checkPlaces, placeOf } from './src/catalog/directory.ts';

import {
  type ArticleEntry,
  checkArticles,
  DEFAULT_LANG,
  hiddenPaths,
  LANGS,
  readFrontmatter,
  sitemapLinks,
} from './src/paths.ts';

/**
 * The public site: the landing page and the articles, built to plain HTML for
 * search engines and link previews, served on konnekt.cz by a container of its
 * own (docker/site/). The catalog pages (/universities/, /chats/, /tutors/) are the
 * exception, rendered on request from the APIs by the Node server the same
 * build produces (`prerender = false` on each). The Mini App is the other
 * build in this package, on its own host.
 *
 * SITE_URL is where the site lives (the deploy passes PUBLIC_SITE_URL), for
 * canonical links, hreflang and the sitemap, which must be absolute. A local
 * build without it gets the dev server's address.
 */

const root = new URL('.', import.meta.url).pathname;

/**
 * The articles as the sitemap needs them: the same files and the same fields
 * the content collection reads, parsed as YAML from the frontmatter alone.
 * Checked here, before any page is built: a reserved slug or a translation
 * key taken twice in one language stops the build.
 */
function articles(): ArticleEntry[] {
  const entries = globSync('src/content/articles/*/*.md', { cwd: root }).map((file) => {
    const text = readFileSync(`${root}${file}`, 'utf8');
    const frontmatter = readFrontmatter(text, file);
    return {
      id: file.replace(/^src\/content\/articles\//, '').replace(/\.md$/, ''),
      draft: frontmatter.draft === true,
      translationKey: String(frontmatter.translationKey),
      people: [frontmatter.author, frontmatter.reviewedBy].filter(Boolean).map(String),
      rubric: String(frontmatter.rubric),
      tags: Array.isArray(frontmatter.tags) ? frontmatter.tags.map(String) : [],
      universities: Array.isArray(frontmatter.universities)
        ? frontmatter.universities.map(String)
        : [],
    };
  });
  const tags = (parse(readFileSync(`${root}src/content/tags.yaml`, 'utf8')) ?? []) as {
    id: string;
  }[];
  checkArticles(
    entries,
    tags.map((tag) => tag.id),
  );
  // The universities' and faculties' texts, by content id: a misplaced file
  // stops the build, and so does an article naming a page with no text.
  const texts = new Map(
    globSync('src/content/universities/*/**/*.md', { cwd: root }).map((file) => {
      const id = file.replace(/^src\/content\/universities\//, '').replace(/\.md$/, '');
      placeOf(id);
      const frontmatter = readFrontmatter(readFileSync(`${root}${file}`, 'utf8'), file);
      return [id, frontmatter.draft === true] as const;
    }),
  );
  for (const entry of entries) checkPlaces(entry, texts);
  return entries;
}

const entries = articles();
const hidden = hiddenPaths(entries);
const building = process.argv.includes('build');
const CATALOG = /^(\/[a-z]{2})?\/(universities|tutors|chats)\//;

const site = process.env.SITE_URL || 'http://localhost:4321';

export default defineConfig({
  site,
  // The icons, one copy for both builds: the Mini App's is web/public/.
  publicDir: '../public',
  // /uk/ and /articles/x/: one address per page, the one the canonical link names.
  // The dev server is what uiux compares with the prototype: no toolbar over the page.
  devToolbar: { enabled: false },
  trailingSlash: 'always',
  build: { format: 'directory' },
  adapter: node({ mode: 'standalone' }),
  // The built server carries everything it imports: its container has no
  // node_modules. The dev server resolves them as usual, and could not load
  // the CommonJS among them bundled.
  vite: { ssr: { noExternal: building || undefined } },
  // An article's notes are its sources, and a table scrolls in its own box (articles/reading.ts).
  // Astro keeps rendered Markdown by the file's content in site/node_modules/.astro, and
  // a plugin's code is not part of that key: after changing reading.ts or texts.ts,
  // delete that directory (and site/.astro) before a local build. CI builds clean.
  // biome-ignore lint/suspicious/noExplicitAny: Sätteri's node types are its own; the plugin reads the shape it needs.
  markdown: { processor: satteri({ hastPlugins: [readingPlugin as any] }) },
  integrations: [
    sitemap({
      // The catalog pages are rendered on request and listed by their own
      // sitemap, which knows which of them may be indexed (sitemap-catalog.xml).
      // The index names it too, for a search engine given only the index.
      customSitemaps: [new URL('/sitemap-catalog.xml', site).href],
      // An article's translations are found by key, not by path (sitemapLinks).
      serialize: (item) => {
        const links = sitemapLinks(new URL(item.url).pathname, entries, hidden, site);
        return links ? { ...item, links } : item;
      },
      filter: (page) => {
        const { pathname } = new URL(page);
        return !hidden.includes(pathname) && !CATALOG.test(pathname);
      },
      i18n: {
        defaultLocale: DEFAULT_LANG,
        locales: Object.fromEntries(LANGS.map((lang) => [lang, lang])),
      },
    }),
  ],
});
