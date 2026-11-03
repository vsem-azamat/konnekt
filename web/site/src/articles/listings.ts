import { DEFAULT_LANG, type Lang, type Listing, listings } from '../paths.ts';
import { entries } from './entries.ts';

/** The rubric or tag pages (`kind`) to build, in Russian or in the other languages. */
export async function listingPaths(kind: Listing['kind'], russian: boolean) {
  const pages = listings(await entries()).filter((page) => page.kind === kind);
  return pages
    .filter((page) => (page.lang === DEFAULT_LANG) === russian)
    .map((page) => ({
      params: { key: page.key, ...(russian ? {} : { lang: page.lang }) },
      props: {
        listing: page,
        langs: pages
          .filter((other) => other.key === page.key)
          .map((other) => other.lang) as Lang[],
      },
    }));
}
