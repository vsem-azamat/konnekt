import { getCollection } from 'astro:content';

import { authorPages, DEFAULT_LANG, type Lang } from '../paths.ts';
import { entries } from './entries.ts';

/**
 * The author pages to build: people only (the editorial team is the site
 * itself), in Russian or in the other languages.
 */
export async function authorPaths(russian: boolean) {
  const people = new Set(
    (await getCollection('authors'))
      .filter((a) => a.data.kind === 'person')
      .map((a) => a.id),
  );
  const pages = authorPages(await entries()).filter((page) => people.has(page.id));
  return pages
    .filter((page) => (page.lang === DEFAULT_LANG) === russian)
    .map((page) => ({
      params: { id: page.id, ...(russian ? {} : { lang: page.lang }) },
      props: {
        id: page.id,
        lang: page.lang,
        hidden: page.hidden,
        langs: pages
          .filter((other) => other.id === page.id)
          .map((other) => other.lang) as Lang[],
      },
    }));
}
