import type { Lang } from './paths.ts';

/**
 * The guide pages' own words. The landing page's, and the header's and
 * footer's, are landing F's (landing/data.ts).
 */
export interface Texts {
  guides: string;
  example: string;
  noGuides: string;
}

export const TEXTS: Record<Lang, Texts> = {
  ru: {
    guides: 'Гайды',
    example: 'Пример',
    noGuides: 'Гайды на этом языке скоро появятся.',
  },
  uk: {
    guides: 'Гайди',
    example: 'Приклад',
    noGuides: 'Гайди цією мовою скоро з’являться.',
  },
  cs: {
    guides: 'Průvodce',
    example: 'Ukázka',
    noGuides: 'Průvodce v tomto jazyce brzy přibudou.',
  },
  en: {
    guides: 'Guides',
    example: 'Example',
    noGuides: 'Guides in this language are coming soon.',
  },
};

/** Open Graph's locale for each language. */
export const OG_LOCALES: Record<Lang, string> = {
  ru: 'ru_RU',
  uk: 'uk_UA',
  cs: 'cs_CZ',
  en: 'en_US',
};
