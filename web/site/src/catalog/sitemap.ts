import type { APIRoute } from 'astro';
import {
  alternates,
  DEFAULT_LANG,
  LANGS,
  type Lang,
  localePath,
  versionsOf,
} from '../paths.ts';
import { universitiesWithChats } from './catalog.ts';
import type { TextPlace } from './directory.ts';
import { placeIndexable, universityAddress } from './directory.ts';
import { CACHED } from './page.ts';
import { publicChats, tutors, universities } from './source.ts';

/**
 * The catalog pages search engines may keep, rendered on request like the
 * pages themselves: /universities/ and /chats/, each university in every
 * language it has our text in or enough chats, each faculty in every
 * language it has our text in (catalog/directory.ts), and the tutors with
 * /tutors/ once there is one, each with its alternates. The
 * built pages have their own sitemap (sitemap-index.xml); robots.txt names
 * both. No lastmod: the catalogue cannot say when a page last changed, and a
 * made-up date teaches a crawler to ignore the field.
 */

const xml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export function catalogSitemap(
  /** The texts there are to show, by place: the content layer's, which node's tests stand in for. */
  textPlaces: () => Promise<readonly { place: TextPlace }[]>,
): APIRoute {
  return async ({ site }) => {
    const origin = (site?.href ?? '/').replace(/\/+$/, '');
    let chatCounts: Map<string, number>;
    let slugs: string[];
    try {
      const [chats, list, people] = await Promise.all([
        publicChats(),
        universities(DEFAULT_LANG),
        // The tutors are a part the rest does not wait on: without them the
        // universities are still worth listing.
        tutors(DEFAULT_LANG).catch((error) => {
          console.error('catalog sitemap: no tutors', error);
          return [];
        }),
      ]);
      chatCounts = new Map(
        universitiesWithChats(list, chats).map(({ university, chats: theirs }) => [
          universityAddress(university.code),
          theirs.length,
        ]),
      );
      // A slug is the same in every language: the name in Latin letters and the id.
      slugs = people.map((row) => row.slug);
    } catch (error) {
      console.error('catalog sitemap: no data', error);
      return new Response(null, {
        status: 503,
        headers: { 'Cache-Control': 'no-store' },
      });
    }
    // Each university's and faculty's languages with our text (no draft: the server built for production shows none).
    const texts = new Map<string, Set<Lang>>();
    for (const { place } of await textPlaces()) {
      const langs = texts.get(place.address) ?? new Set<Lang>();
      langs.add(place.lang);
      texts.set(place.address, langs);
    }
    const places = [...new Set([...chatCounts.keys(), ...texts.keys()])].map(
      (address) => ({
        path: `/universities/${address}/`,
        langs: LANGS.filter((lang) =>
          address.includes('/')
            ? (texts.get(address)?.has(lang) ?? false)
            : placeIndexable(
                texts.get(address)?.has(lang) ?? false,
                chatCounts.get(address) ?? 0,
              ),
        ),
      }),
    );
    const pages: { path: string; langs: readonly Lang[] }[] = [
      ...['/universities/', '/chats/'].map((path) => ({ path, langs: LANGS })),
      ...places.filter((place) => place.langs.length > 0),
      ...(slugs.length
        ? ['/tutors/', ...slugs.map((slug) => `/tutors/${slug}/`)].map((path) => ({
            path,
            langs: LANGS,
          }))
        : []),
    ];
    const urls = pages.flatMap(({ path, langs }) =>
      langs.map((lang) => {
        const links = alternates(versionsOf(path, langs), origin)
          .map(
            ({ hreflang, href }) =>
              `<xhtml:link rel="alternate" hreflang="${hreflang}" href="${xml(href)}"/>`,
          )
          .join('');
        return `<url><loc>${xml(`${origin}${localePath(lang, path)}`)}</loc>${links}</url>`;
      }),
    );
    return new Response(
      `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">${urls.join('')}</urlset>\n`,
      {
        headers: {
          'Content-Type': 'application/xml; charset=utf-8',
          'Cache-Control': CACHED,
        },
      },
    );
  };
}
