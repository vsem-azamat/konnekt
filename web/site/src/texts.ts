import type { Lang } from './paths.ts';

/**
 * The article pages' own words. The landing page's, and the header's and
 * footer's, are landing F's (landing/data.ts).
 */
export interface Texts {
  articles: string;
  example: string;
  noArticles: string;
}

export const TEXTS: Record<Lang, Texts> = {
  ru: {
    articles: 'Статьи',
    example: 'Пример',
    noArticles: 'Статьи на этом языке скоро появятся.',
  },
  uk: {
    articles: 'Статті',
    example: 'Приклад',
    noArticles: 'Статті цією мовою скоро з’являться.',
  },
  cs: {
    articles: 'Články',
    example: 'Ukázka',
    noArticles: 'Články v tomto jazyce brzy přibudou.',
  },
  en: {
    articles: 'Articles',
    example: 'Example',
    noArticles: 'Articles in this language are coming soon.',
  },
};

/** Open Graph's locale for each language. */
export const OG_LOCALES: Record<Lang, string> = {
  ru: 'ru_RU',
  uk: 'uk_UA',
  cs: 'cs_CZ',
  en: 'en_US',
};
