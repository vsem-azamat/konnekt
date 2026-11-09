import { defineCollection, reference } from 'astro:content';
import { file, glob } from 'astro/loaders';
import { z } from 'astro/zod';

import { LOGO_IDS } from './articles/logos.ts';
import { LANGS, RUBRICS, SLUG } from './paths.ts';

const slug = z.string().regex(SLUG, 'lowercase latin words joined by hyphens');
// A link the page writes into an href: a web page, never javascript: or mailto:.
const https = z.string().url().startsWith('https://');

const sources = z
  .array(
    z.object({
      url: z.string().url(),
      title: z.string().min(1),
      // When the page was last read to confirm what the text takes from it.
      checked_at: z.coerce.date(),
    }),
  )
  .default([]);

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
        // From content/tags.yaml, where a tag gets its name in each language.
        tags: z.array(reference('tags')).default([]),
        translationKey: slug,
        published: z.coerce.date(),
        // Moved only by a change of substance, not a typo: it is what readers
        // and search engines are told.
        updated: z.coerce.date().optional(),
        author: reference('authors'),
        // Who checked the facts, named on the page as such.
        reviewedBy: reference('authors').optional(),
        sources,
        // The article's image, one for all its languages:
        // assets/covers/<translationKey>.jpg. The page shows it above the text,
        // and the card a link shows (articles/og.ts) shows part of it.
        cover: image().optional(),
        coverAlt: z.string().min(1).optional(),
        // Where across the image (0 the left edge, 1 the right) the card's
        // narrower frame is centred: on what the image is of.
        coverFocus: z.number().min(0).max(1).default(0.5),
        // The schools' own logos laid over it (articles/logos.ts), never drawn
        // into the image itself.
        coverLogos: z
          .array(z.enum(LOGO_IDS))
          .max(6)
          .refine((ids) => new Set(ids).size === ids.length, 'a logo named twice')
          .default([]),
        // Whose photo it is, for a real one (Wikimedia Commons and the like),
        // as its licence asks; a generated image has none.
        coverCredit: z
          .object({
            author: z.string().min(1),
            licence: z.string().min(1),
            // The licence's own text, which CC licences ask a credit to link.
            licenceUrl: https.optional(),
            source: https,
            // Whether part of the photo was cut away, which CC BY asks a credit
            // to say. A 3:2 photo only shrinks to the 3:2 cover; the image
            // skill sets false then.
            cropped: z.boolean().default(true),
          })
          .optional(),
        // The universities and faculties it is about, by their pages'
        // addresses (`cvut`, `cvut/fit`): each lists it, and it lists them.
        // The config checks each has a text in the article's language.
        universities: z
          .array(z.string().regex(/^[a-z0-9-]+(?:\/[a-z0-9-]+)?$/, 'cvut or cvut/fit'))
          .default([]),
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
        if (!article.cover && (article.coverLogos.length > 0 || article.coverCredit)) {
          ctx.addIssue({
            code: 'custom',
            path: ['cover'],
            message: 'logos and a credit go on a cover, and there is none',
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
    // A line or two on who they are, in each language their page is in.
    bio: z.partialRecord(z.enum(LANGS), z.string().min(1)).default({}),
    links: z.array(z.string().url()).default([]),
  }),
});

/**
 * The tags, in one file (`content/tags.yaml`): the id is the tag's address,
 * `names` what a reader sees. An article may carry only a tag listed here.
 */
const tags = defineCollection({
  loader: file('src/content/tags.yaml'),
  schema: z.object({
    id: slug,
    names: z.partialRecord(z.enum(LANGS), z.string().min(1)),
  }),
});

/**
 * Our own text about a university or a faculty (catalog/directory.ts):
 * `universities/<lang>/<university>.md` and
 * `universities/<lang>/<university>/<faculty>.md`, the file's path its
 * page's address. What changes every year (deadlines, fees) goes into
 * articles that name the page; this is what stays true.
 *
 * A draft is shown only by the dev server: a text nobody checked never
 * reaches the public page, which stays as it was until it is.
 */
const universities = defineCollection({
  loader: glob({ pattern: '*/**/*.md', base: './src/content/universities' }),
  schema: z
    .object({
      // The page's heading: «ЧВУТ — Чешский технический университет в Праге».
      name: z.string().min(3).max(120),
      // Its abbreviation as it writes it, on its tile and in breadcrumbs:
      // «ČVUT», «FSv». Its address in capitals when left out.
      short: z.string().min(1).max(8).optional(),
      // What a search result shows as its title; the site's name is not added.
      title: z.string().min(10).max(70),
      description: z.string().min(50).max(170),
      // Its own official site.
      website: https,
      // Moved only by a change of substance, as an article's.
      updated: z.coerce.date(),
      author: reference('authors'),
      reviewedBy: reference('authors').optional(),
      sources,
      // A faculty's chats, by their public links: the catalogue's chats name
      // their university and not their faculty.
      chats: z.array(https).default([]),
      draft: z.boolean().default(false),
    })
    .superRefine((text, ctx) => {
      if (text.draft) return;
      if (!text.reviewedBy) {
        ctx.addIssue({
          code: 'custom',
          path: ['reviewedBy'],
          message: 'a published text is checked by someone',
        });
      }
      if (text.sources.length === 0) {
        ctx.addIssue({
          code: 'custom',
          path: ['sources'],
          message: 'a published text names its sources',
        });
      }
    }),
});

export const collections = { articles, authors, tags, universities };
