import { defineCollection, reference } from 'astro:content';
import { glob } from 'astro/loaders';
import { z } from 'astro/zod';

import { LANGS } from './paths.ts';

/** The sections an article belongs to, one each; their names are in texts.ts. */
export const RUBRICS = ['admission', 'visa', 'housing', 'study', 'work'] as const;

const slug = z
  .string()
  .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, 'lowercase latin words joined by hyphens');

/**
 * Articles, one Markdown file per language: `articles/<lang>/<slug>.md`, the
 * slug in that language. Translations of one article share `translationKey`,
 * which is how hreflang finds them. `draft` marks an example: shown with a
 * badge, kept out of search, and spared the fields a published article must
 * have.
 *
 * The fields are the ones a CMS collection would have (Payload's, should the
 * articles move into one), each a value of its own rather than prose.
 */
const articles = defineCollection({
  loader: glob({ pattern: '*/*.md', base: './src/content/articles' }),
  schema: ({ image }) =>
    z
      .object({
        title: z.string().min(10).max(90),
        // What a search result shows under the title: cut beyond about 160.
        description: z.string().min(50).max(170),
        // A guide stays true until it is updated; news is of its day, and
        // only news gets NewsArticle and the news sitemap.
        type: z.enum(['guide', 'news']).default('guide'),
        rubric: z.enum(RUBRICS),
        tags: z.array(slug).default([]),
        translationKey: slug,
        published: z.coerce.date(),
        // Moved only by a change of substance, not a typo: it is what readers
        // and search engines are told.
        updated: z.coerce.date().optional(),
        author: reference('authors'),
        // Who checked the facts, named on the page as such.
        reviewedBy: reference('authors').optional(),
        sources: z
          .array(
            z.object({
              url: z.string().url(),
              title: z.string().min(1),
              // When the page was last read to confirm what the article takes from it.
              checked_at: z.coerce.date(),
            }),
          )
          .default([]),
        cover: image().optional(),
        coverAlt: z.string().min(1).optional(),
        draft: z.boolean().default(false),
      })
      .superRefine((article, ctx) => {
        if (article.updated && article.updated < article.published) {
          ctx.addIssue({
            code: 'custom',
            path: ['updated'],
            message: 'before published',
          });
        }
        if (article.cover && !article.coverAlt) {
          ctx.addIssue({
            code: 'custom',
            path: ['coverAlt'],
            message: 'a cover needs its alt text',
          });
        }
        if (article.draft) return;
        if (!article.reviewedBy) {
          ctx.addIssue({
            code: 'custom',
            path: ['reviewedBy'],
            message: 'a published article is checked by someone',
          });
        }
        if (article.sources.length === 0) {
          ctx.addIssue({
            code: 'custom',
            path: ['sources'],
            message: 'a published article names its sources',
          });
        }
      }),
});

/**
 * Who writes and who checks: `authors/<id>.yaml`, a real person or the
 * editorial team itself, never an invented one. `name` is the default; `names`
 * gives it in a language that writes it otherwise.
 */
const authors = defineCollection({
  loader: glob({ pattern: '*.yaml', base: './src/content/authors' }),
  schema: z.object({
    kind: z.enum(['person', 'organization']),
    name: z.string().min(1),
    names: z.partialRecord(z.enum(LANGS), z.string().min(1)).default({}),
    links: z.array(z.string().url()).default([]),
  }),
});

export const collections = { articles, authors };
