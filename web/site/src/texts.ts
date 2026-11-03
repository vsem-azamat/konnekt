import type { Lang, Rubric } from './paths.ts';

/**
 * The article pages' own words. The landing page's, and the header's and
 * footer's, are landing F's (landing/data.ts).
 */
export interface Texts {
  articles: string;
  example: string;
  noArticles: string;
  rubrics: Record<Rubric, string>;
  author: string;
  reviewedBy: string;
  published: string;
  updated: string;
  sources: string;
  /** Before the day a source was last read: «проверено 3 ноября 2026». */
  checked: string;
  wrote: string;
  checkedArticles: string;
}

export const TEXTS: Record<Lang, Texts> = {
  ru: {
    articles: 'Статьи',
    example: 'Пример',
    noArticles: 'Статьи на этом языке скоро появятся.',

    rubrics: {
      admission: 'Поступление',
      visa: 'Виза и ВНЖ',
      housing: 'Жильё',
      study: 'Учёба',
      work: 'Работа и деньги',
    },
    author: 'Автор',
    reviewedBy: 'Проверил',
    published: 'Опубликовано',
    updated: 'Обновлено',
    sources: 'Источники',
    checked: 'проверено',
    wrote: 'Статьи',
    checkedArticles: 'Проверенные статьи',
  },
  uk: {
    articles: 'Статті',
    example: 'Приклад',
    noArticles: 'Статті цією мовою скоро з’являться.',

    rubrics: {
      admission: 'Вступ',
      visa: 'Віза і посвідка',
      housing: 'Житло',
      study: 'Навчання',
      work: 'Робота і гроші',
    },
    author: 'Автор',
    reviewedBy: 'Перевірив',
    published: 'Опубліковано',
    updated: 'Оновлено',
    sources: 'Джерела',
    checked: 'перевірено',
    wrote: 'Статті',
    checkedArticles: 'Перевірені статті',
  },
  cs: {
    articles: 'Články',
    example: 'Ukázka',
    noArticles: 'Články v tomto jazyce brzy přibudou.',

    rubrics: {
      admission: 'Přijímací řízení',
      visa: 'Víza a pobyt',
      housing: 'Bydlení',
      study: 'Studium',
      work: 'Práce a peníze',
    },
    author: 'Autor',
    reviewedBy: 'Zkontroloval',
    published: 'Publikováno',
    updated: 'Aktualizováno',
    sources: 'Zdroje',
    checked: 'ověřeno',
    wrote: 'Články',
    checkedArticles: 'Zkontrolované články',
  },
  en: {
    articles: 'Articles',
    example: 'Example',
    noArticles: 'Articles in this language are coming soon.',

    rubrics: {
      admission: 'Admission',
      visa: 'Visa and residence',
      housing: 'Housing',
      study: 'Study',
      work: 'Work and money',
    },
    author: 'Author',
    reviewedBy: 'Reviewed by',
    published: 'Published',
    updated: 'Updated',
    sources: 'Sources',
    checked: 'checked',
    wrote: 'Articles',
    checkedArticles: 'Reviewed articles',
  },
};

/** A day as the page shows it: «3 ноября 2026». Frontmatter dates are UTC midnight. */
export function longDate(lang: Lang, date: Date): string {
  return new Intl.DateTimeFormat(lang, {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(date);
}

/** Open Graph's locale for each language. */
export const OG_LOCALES: Record<Lang, string> = {
  ru: 'ru_RU',
  uk: 'uk_UA',
  cs: 'cs_CZ',
  en: 'en_US',
};
