import type { APIRoute } from 'astro';

import { indexable, universitiesWithChats } from '../catalog/catalog.ts';
import { CACHED } from '../catalog/page.ts';
import { publicChats, tutors, universities } from '../catalog/source.ts';
import { alternates, DEFAULT_LANG, LANGS, localePath, versionsOf } from '../paths.ts';

/**
 * The catalog pages search engines may keep, rendered on request like the
 * pages themselves: /universities/ and /chats/, each university with enough
 * chats to be indexed, and the tutors with /tutors/ once there is one, in
 * every language with its alternates. The
 * built pages have their own sitemap (sitemap-index.xml); robots.txt names
 * both. No lastmod: the catalogue cannot say when a page last changed, and a
 * made-up date teaches a crawler to ignore the field.
 */
export const prerender = false;

const xml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export const GET: APIRoute = async ({ site }) => {
  const origin = (site?.href ?? '/').replace(/\/+$/, '');
  let codes: string[];
  let slugs: string[];
  try {
    const [chats, list, people] = await Promise.all([
      publicChats(),
      universities(DEFAULT_LANG),
      tutors(DEFAULT_LANG),
    ]);
    codes = universitiesWithChats(list, chats)
      .filter(indexable)
      .map(({ university }) => university.code);
    // A slug is the same in every language: the name in Latin letters and the id.
    slugs = people.map((row) => row.slug);
  } catch (error) {
    console.error('catalog sitemap: no data', error);
    return new Response(null, { status: 503, headers: { 'Cache-Control': 'no-store' } });
  }
  const paths = [
    '/universities/',
    '/chats/',
    ...codes.map((code) => `/universities/${code}/`),
    ...(slugs.length ? ['/tutors/', ...slugs.map((slug) => `/tutors/${slug}/`)] : []),
  ];
  const urls = paths.flatMap((path) =>
    LANGS.map((lang) => {
      const links = alternates(versionsOf(path, LANGS), origin)
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
