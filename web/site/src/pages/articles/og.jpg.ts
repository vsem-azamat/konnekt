/** The card a link to the Russian articles, a rubric or a tag shows (articles/og.ts). */
import type { APIRoute } from 'astro';

import { jpeg, listCard } from '../../articles/cards.ts';

export const GET: APIRoute = async () => jpeg(await listCard('ru'));
