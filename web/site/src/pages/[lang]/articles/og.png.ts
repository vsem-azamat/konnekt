/** The card a link to the articles in another language shows (articles/og.ts). */
import type { APIRoute, GetStaticPaths } from 'astro';

import { listCard, png } from '../../../articles/cards.ts';
import { DEFAULT_LANG, LANGS, type Lang } from '../../../paths.ts';

export const getStaticPaths = (() =>
  LANGS.filter((lang) => lang !== DEFAULT_LANG).map((lang) => ({
    params: { lang },
  }))) satisfies GetStaticPaths;

export const GET: APIRoute = async ({ params }) =>
  png(await listCard(params.lang as Lang));
