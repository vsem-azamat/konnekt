/** The card a link to a Russian article shows (articles/og.ts). */

import { type CollectionEntry, getCollection } from 'astro:content';
import type { APIRoute, GetStaticPaths } from 'astro';

import { articleCard, jpeg } from '../../../articles/cards.ts';
import { DEFAULT_LANG, langOf, slugOf } from '../../../paths.ts';

export const getStaticPaths = (async () => {
  const articles = await getCollection('articles');
  return articles
    .filter((article) => langOf(article.id) === DEFAULT_LANG)
    .map((article) => ({ params: { slug: slugOf(article.id) }, props: { article } }));
}) satisfies GetStaticPaths;

export const GET: APIRoute = async ({ props }) =>
  jpeg(await articleCard((props as { article: CollectionEntry<'articles'> }).article));
