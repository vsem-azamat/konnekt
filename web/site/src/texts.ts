import type { Lang } from './paths.ts';

/**
 * The site's words in each language.
 *
 * The landing's are the ones the Mini App showed a browser until this site
 * existed (web/src/locales), already reviewed in all four languages. They hold
 * the place until the new landing replaces them.
 */
export interface Texts {
  title: string;
  description: string;
  headline: string;
  sub: string;
  chips: readonly string[];
  cta: string;
  foot: string;
  guides: string;
  example: string;
  noGuides: string;
  language: string;
}

export const TEXTS: Record<Lang, Texts> = {
  ru: {
    title: 'Konnekt — студенческие чаты и помощь с учёбой в Чехии',
    description:
      'Чаты студентов чешских вузов и люди, которые помогут с учёбой: репетиторы, подготовка к вступительным экзаменам, нострификация. Открывается в Telegram.',
    headline: 'Кто поможет с учёбой в Чехии',
    sub: 'Репетиторы, подготовка к вступительным экзаменам, помощь на экзамене и нострификация — от студентов, которые это уже прошли.',
    chips: ['Репетиторы', 'Вступительные экзамены', 'Нострификация', 'Работы'],
    cta: 'Открыть в Telegram',
    foot: 'Регистрации нет — заходишь своим аккаунтом Telegram. Помогать другим можно оттуда же.',
    guides: 'Гайды',
    example: 'Пример',
    noGuides: 'Гайды на этом языке скоро появятся.',
    language: 'Язык',
  },
  uk: {
    title: 'Konnekt — Хто допоможе з навчанням у Чехії',
    description:
      'Репетитори, підготовка до вступних іспитів, допомога на іспиті та нострифікація — від студентів, які це вже пройшли.',
    headline: 'Хто допоможе з навчанням у Чехії',
    sub: 'Репетитори, підготовка до вступних іспитів, допомога на іспиті та нострифікація — від студентів, які це вже пройшли.',
    chips: ['Репетитори', 'Вступні іспити', 'Нострифікація', 'Роботи'],
    cta: 'Відкрити в Telegram',
    foot: 'Реєстрації немає — заходиш своїм акаунтом Telegram. Допомагати іншим можна звідти ж.',
    guides: 'Гайди',
    example: 'Приклад',
    noGuides: 'Гайди цією мовою скоро з’являться.',
    language: 'Мова',
  },
  cs: {
    title: 'Konnekt — Kdo pomůže se studiem v Česku',
    description:
      'Doučování, příprava na přijímací zkoušky, pomoc u zkoušky a nostrifikace — od studentů, kteří si tím prošli.',
    headline: 'Kdo pomůže se studiem v Česku',
    sub: 'Doučování, příprava na přijímací zkoušky, pomoc u zkoušky a nostrifikace — od studentů, kteří si tím prošli.',
    chips: ['Doučování', 'Přijímací zkoušky', 'Nostrifikace', 'Práce'],
    cta: 'Otevřít v Telegramu',
    foot: 'Žádná registrace — přihlásíš se svým účtem na Telegramu. Pomáhat ostatním můžeš odtamtud taky.',
    guides: 'Průvodce',
    example: 'Ukázka',
    noGuides: 'Průvodce v tomto jazyce brzy přibudou.',
    language: 'Jazyk',
  },
  en: {
    title: 'Konnekt — Who can help you study in Czechia',
    description:
      'Tutors, entrance exam prep, help at the exam and nostrification — from students who have been through it.',
    headline: 'Who can help you study in Czechia',
    sub: 'Tutors, entrance exam prep, help at the exam and nostrification — from students who have been through it.',
    chips: ['Tutors', 'Entrance exams', 'Nostrification', 'Written work'],
    cta: 'Open in Telegram',
    foot: 'No sign-up — you come in with your Telegram account. Helping others starts in the same place.',
    guides: 'Guides',
    example: 'Example',
    noGuides: 'Guides in this language are coming soon.',
    language: 'Language',
  },
};

/** Each language by its own name, for the switcher. */
export const LANG_NAMES: Record<Lang, string> = {
  ru: 'Русский',
  uk: 'Українська',
  cs: 'Čeština',
  en: 'English',
};
