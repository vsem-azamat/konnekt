import { globSync, readFileSync } from 'node:fs';
import node from '@astrojs/node';
import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';
import { parse } from 'yaml';

import { DEFAULT_LANG, type GuideEntry, hiddenPaths, LANGS } from './src/paths.ts';

/**
 * The public site: the landing page and the guides, built to plain HTML for
 * search engines and link previews, served on konnekt.cz by a container of its
 * own (docker/site/). The catalog pages (/universities/, /chats/) are the
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
 * The guides as the sitemap needs them: the same files and the same `draft`
 * field the content collection reads, parsed as YAML from the frontmatter alone.
 */
function guides(): GuideEntry[] {
  return globSync('src/content/guides/*/*.md', { cwd: root }).map((file) => {
    const text = readFileSync(`${root}${file}`, 'utf8');
    const frontmatter = text.match(/^---\r?\n([\s\S]*?)\r?\n---/)?.[1] ?? '';
    return {
      id: file.replace(/^src\/content\/guides\//, '').replace(/\.md$/, ''),
      draft: parse(frontmatter)?.draft === true,
    };
  });
}

const hidden = hiddenPaths(guides());
const building = process.argv.includes('build');
const CATALOG = /^(\/[a-z]{2})?\/(universities|chats)\//;

export default defineConfig({
  site: process.env.SITE_URL || 'http://localhost:4321',
  // /uk/ and /guides/x/: one address per page, the one the canonical link names.
  // The dev server is what uiux compares with the prototype: no toolbar over the page.
  devToolbar: { enabled: false },
  trailingSlash: 'always',
  build: { format: 'directory' },
  adapter: node({ mode: 'standalone' }),
  // The built server carries everything it imports: its container has no
  // node_modules. The dev server resolves them as usual, and could not load
  // the CommonJS among them bundled.
  vite: { ssr: { noExternal: building || undefined } },
  integrations: [
    sitemap({
      // The catalog pages are rendered on request and listed by their own
      // sitemap, which knows which of them may be indexed (sitemap-catalog.xml).
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
