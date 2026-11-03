import { type CollectionEntry, getCollection } from 'astro:content';

import { type Lang, langOf } from '../paths.ts';

/** The published articles in `lang`, newest first. */
export async function published(lang: Lang): Promise<CollectionEntry<'articles'>[]> {
  return (await getCollection('articles'))
    .filter((article) => !article.data.draft && langOf(article.id) === lang)
    .sort((a, b) => b.data.published.valueOf() - a.data.published.valueOf());
}
