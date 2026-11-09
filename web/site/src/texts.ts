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
  /** A rubric's page, under its name: what it is about. */
  rubricIntros: Record<Rubric, string>;
  readNext: string;
  tags: string;
  /** Above a tag's articles: «Статьи с тегом». */
  tagged: string;
  /** A footnote's way back to where it is cited, for a screen reader. */
  backToText: string;
  contents: string;
  /** The title of the card a link to the articles shows: «Статьи Konnekt». */
  cardTitle: string;
  /** Before a photo's author, under it: «Фото». */
  photo: string;
  /** After a photo's licence when part of it was cut away: CC BY asks that a change be said. */
  cropped: string;
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

    rubricIntros: {
      admission:
        'Как выбрать вуз в Чехии, подать документы, сдать экзамены и нострифицировать аттестат.',
      visa: 'Студенческая виза, ВНЖ, продление и всё, что для них нужно от МВД.',
      housing: 'Общежития, съём квартиры, договоры и прописка.',
      study: 'Учёба в чешском вузе: семестры, экзамены, кредиты, языковые курсы.',
      work: 'Подработка во время учёбы, налоги, банк и деньги на жизнь.',
    },
    readNext: 'Читайте также',
    tags: 'Теги',
    tagged: 'Статьи с тегом',
    backToText: 'Назад к тексту',
    contents: 'Содержание',
    cardTitle: 'Статьи Konnekt',
    photo: 'Фото',
    cropped: 'кадрировано',
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

    rubricIntros: {
      admission:
        'Як обрати виш у Чехії, подати документи, скласти іспити й нострифікувати атестат.',
      visa: 'Студентська віза, посвідка на проживання, продовження і все, що для них потрібно від МВС.',
      housing: 'Гуртожитки, оренда квартири, договори й реєстрація.',
      study: 'Навчання в чеському виші: семестри, іспити, кредити, мовні курси.',
      work: 'Підробіток під час навчання, податки, банк і гроші на життя.',
    },
    readNext: 'Читайте також',
    tags: 'Теги',
    tagged: 'Статті з тегом',
    backToText: 'Назад до тексту',
    contents: 'Зміст',
    cardTitle: 'Статті Konnekt',
    photo: 'Фото',
    cropped: 'кадровано',
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

    rubricIntros: {
      admission:
        'Jak vybrat vysokou školu v Česku, podat přihlášku, složit zkoušky a nostrifikovat maturitu.',
      visa: 'Studentské vízum, povolení k pobytu, prodloužení a co k nim chce ministerstvo vnitra.',
      housing: 'Koleje, pronájem bytu, smlouvy a hlášení pobytu.',
      study: 'Studium na české vysoké škole: semestry, zkoušky, kredity, jazykové kurzy.',
      work: 'Brigády při studiu, daně, banka a peníze na život.',
    },
    readNext: 'Číst dál',
    tags: 'Štítky',
    tagged: 'Články se štítkem',
    backToText: 'Zpět do textu',
    contents: 'Obsah',
    cardTitle: 'Články Konnekt',
    photo: 'Foto',
    cropped: 'oříznuto',
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

    rubricIntros: {
      admission:
        'Choosing a university in Czechia, applying, passing the exams and recognising your school diploma.',
      visa: 'The student visa, residence permits, extensions and what the Ministry of the Interior asks for them.',
      housing: 'Dormitories, renting a flat, contracts and registering your address.',
      study:
        'Studying at a Czech university: semesters, exams, credits, language courses.',
      work: 'Part-time work while studying, taxes, banking and money to live on.',
    },
    readNext: 'Read next',
    tags: 'Tags',
    tagged: 'Articles tagged',
    backToText: 'Back to the text',
    contents: 'Contents',
    cardTitle: 'Konnekt articles',
    photo: 'Photo',
    cropped: 'cropped',
  },
};

/** «3 статьи», «5 статей»: each language's forms, `#` for the number. */
const ARTICLE_COUNT: Record<Lang, Partial<Record<Intl.LDMLPluralRule, string>>> = {
  ru: { one: '# статья', few: '# статьи', many: '# статей', other: '# статьи' },
  uk: { one: '# стаття', few: '# статті', many: '# статей', other: '# статті' },
  cs: { one: '# článek', few: '# články', many: '# článku', other: '# článků' },
  en: { one: '# article', other: '# articles' },
};

/** How many articles there are, in the form the number asks for. */
export function articleCount(lang: Lang, n: number): string {
  const forms = ARTICLE_COUNT[lang];
  const form = forms[new Intl.PluralRules(lang).select(n)] ?? forms.other ?? '#';
  return form.replace('#', String(n));
}

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
