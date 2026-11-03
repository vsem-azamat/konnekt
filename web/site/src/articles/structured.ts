/**
 * What an article's page tells search engines in schema.org's terms, as
 * JSON-LD: the article, the page it is on and who checked it, the way back
 * up the site, and Konnekt as the publisher. Pure, so the tests read the
 * same objects the page prints.
 */

import type { Lang } from '../paths.ts';

export interface Party {
  kind: 'person' | 'organization';
  name: string;
  /** Their page on the site; the editorial team has none. */
  url?: string;
}

export interface Crumb {
  name: string;
  url: string;
}

export interface ArticleFacts {
  type: 'guide' | 'news';
  url: string;
  lang: Lang;
  headline: string;
  description: string;
  published: Date;
  updated?: Date;
  author: Party;
  reviewer?: Party;
  image?: string;
  /** The pages above this one, from the home page down. */
  crumbs: readonly Crumb[];
}

type Graph = { '@context': 'https://schema.org'; '@graph': Record<string, unknown>[] };

/** A date as schema.org reads one, the day alone; frontmatter dates are UTC midnight. */
export function day(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function party({ kind, name, url }: Party): Record<string, unknown> {
  return {
    '@type': kind === 'person' ? 'Person' : 'Organization',
    name,
    ...(url && { url }),
  };
}

function publisher(site: string): Record<string, unknown> {
  return {
    '@type': 'Organization',
    '@id': new URL('/#organization', site).href,
    name: 'Konnekt',
    url: new URL('/', site).href,
    logo: new URL('/apple-touch-icon.png', site).href,
  };
}

export function articleGraph(article: ArticleFacts, site: string): Graph {
  const org = publisher(site);
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        // News is of its day; a guide stays true until it is updated.
        '@type': article.type === 'news' ? 'NewsArticle' : 'Article',
        '@id': `${article.url}#article`,
        headline: article.headline,
        description: article.description,
        inLanguage: article.lang,
        datePublished: day(article.published),
        dateModified: day(article.updated ?? article.published),
        author: party(article.author),
        publisher: { '@id': org['@id'] },
        mainEntityOfPage: { '@id': article.url },
        ...(article.image && { image: article.image }),
      },
      {
        '@type': 'WebPage',
        '@id': article.url,
        url: article.url,
        name: article.headline,
        inLanguage: article.lang,
        breadcrumb: { '@id': `${article.url}#breadcrumb` },
        // Who checked the facts: the page's reviewer, which Article has no word for.
        ...(article.reviewer && { reviewedBy: party(article.reviewer) }),
      },
      {
        '@type': 'BreadcrumbList',
        '@id': `${article.url}#breadcrumb`,
        itemListElement: [
          ...article.crumbs.map((crumb, index) => ({
            '@type': 'ListItem',
            position: index + 1,
            name: crumb.name,
            item: crumb.url,
          })),
          {
            '@type': 'ListItem',
            position: article.crumbs.length + 1,
            name: article.headline,
          },
        ],
      },
      org,
    ],
  };
}

/** An author's page: the person and the places that are theirs elsewhere. */
export function profileGraph(person: Party & { links: readonly string[] }): Graph {
  return {
    '@context': 'https://schema.org',
    '@graph': [
      {
        '@type': 'ProfilePage',
        ...(person.url && { url: person.url }),
        mainEntity: {
          ...party(person),
          ...(person.links.length > 0 && { sameAs: [...person.links] }),
        },
      },
    ],
  };
}

/** JSON for a script element: a `<` inside a string cannot end it early. */
export function jsonLd(value: unknown): string {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}
