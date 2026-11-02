import { globSync, readFileSync } from 'node:fs';
import sitemap from '@astrojs/sitemap';
import { defineConfig } from 'astro/config';

import { DEFAULT_LANG, type GuideEntry, hiddenPaths, LANGS } from './src/paths.ts';

/**
 * The public site: the landing page and the guides, built to plain HTML for
 * search engines and link previews. The Mini App is the other build in this
 * package; docker/Caddyfile serves each its own paths on the same host.
 *
 * SITE_URL is where the site lives (the deploy passes WEBAPI_PUBLIC_URL), for
 * canonical links, hreflang and the sitemap, which must be absolute. A local
 * build without it gets the dev server's address.
 */

const root = new URL('.', import.meta.url).pathname;

/** The guides as the sitemap needs them, read the way the content collection reads them. */
function guides(): GuideEntry[] {
  return globSync('src/content/guides/*/*.md', { cwd: root }).map((file) => ({
    id: file.replace(/^src\/content\/guides\//, '').replace(/\.md$/, ''),
    draft: /^draft:\s*true\s*$/m.test(readFileSync(`${root}${file}`, 'utf8')),
  }));
}

const hidden = hiddenPaths(guides());

export default defineConfig({
  site: process.env.SITE_URL || 'http://localhost:4321',
  // /uk/ and /guides/x/: one address per page, the one the canonical link names.
  trailingSlash: 'always',
  build: { format: 'directory' },
  integrations: [
    sitemap({
      filter: (page) => !hidden.includes(new URL(page).pathname),
      i18n: {
        defaultLocale: DEFAULT_LANG,
        locales: Object.fromEntries(LANGS.map((lang) => [lang, lang])),
      },
    }),
  ],
});
