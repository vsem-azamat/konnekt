import { defineCollection } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

/**
 * Guides, one Markdown file per language: `guides/<lang>/<slug>.md`. A
 * translation has the same slug as the original, which is how hreflang finds
 * it. `draft` marks an example: shown with a badge, kept out of search.
 */
const guides = defineCollection({
  loader: glob({ pattern: '*/*.md', base: './src/content/guides' }),
  schema: z.object({
    title: z.string(),
    description: z.string(),
    draft: z.boolean().default(false),
  }),
});

export const collections = { guides };
