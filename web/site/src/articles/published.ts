import { type CollectionEntry, getCollection } from 'astro:content';

import { type Lang, newestPublished } from '../paths.ts';

/** The published articles in `lang`, newest first (newestPublished on the collection). */
export async function published(lang: Lang): Promise<CollectionEntry<'articles'>[]> {
  const articles = (await getCollection('articles')).map((article) => ({
    article,
    id: article.id,
    draft: article.data.draft,
    published: article.data.published,
  }));
  return newestPublished(articles, lang).map(({ article }) => article);
}
