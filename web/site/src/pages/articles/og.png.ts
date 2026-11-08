/** The card a link to the Russian articles, a rubric or a tag shows (articles/og.ts). */
import type { APIRoute } from 'astro';

import { listCard, png } from '../../articles/cards.ts';

export const GET: APIRoute = async () => png(await listCard('ru'));
