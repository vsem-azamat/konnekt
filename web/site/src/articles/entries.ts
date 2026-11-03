import { type CollectionEntry, getCollection } from 'astro:content';

import type { ArticleEntry } from '../paths.ts';

/** An article as the path functions see it. */
export function entry({ id, data }: CollectionEntry<'articles'>): ArticleEntry {
  return {
    id,
    draft: data.draft,
    translationKey: data.translationKey,
    people: [data.author.id, ...(data.reviewedBy ? [data.reviewedBy.id] : [])],
    rubric: data.rubric,
    tags: data.tags.map((tag) => tag.id),
  };
}

export async function entries(): Promise<ArticleEntry[]> {
  return (await getCollection('articles')).map(entry);
}
