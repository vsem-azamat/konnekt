/** The card a link to the articles in another language shows (articles/og.ts). */
import type { APIRoute, GetStaticPaths } from 'astro';

import { jpeg, listCard } from '../../../articles/cards.ts';
import { DEFAULT_LANG, LANGS, type Lang } from '../../../paths.ts';

export const getStaticPaths = (() =>
  LANGS.filter((lang) => lang !== DEFAULT_LANG).map((lang) => ({
    params: { lang },
  }))) satisfies GetStaticPaths;

export const GET: APIRoute = async ({ params }) =>
  jpeg(await listCard(params.lang as Lang));
