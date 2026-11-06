/**
 * The tutors' pages' own words in each language. A tutor's name, headline,
 * text and offers are theirs and stay as they wrote them.
 */

import type { Lang } from '../paths.ts';
import type { WorkFormat } from './tutors.ts';

export interface TutorTexts {
  section: string;
  title: string;
  description: string;
  h1: string;
  lead: string;
  emptyTitle: string;
  emptyText: string;
  become: string;
  from: string;
  formats: Record<WorkFormat, string>;
  about: string;
  offers: string;
  langs: string;
  write: string;
  writeNote: string;
  pageTitle: (name: string, what: string | null) => string;
  pageDescription: (name: string, what: string) => string;
  all: string;
}

export const TUTOR_TEXTS: Record<Lang, TutorTexts> = {
  ru: {
    section: 'Репетиторы',
    title: 'Репетиторы для студентов в Чехии — Konnekt',
    description:
      'Студенты и выпускники чешских вузов помогают с учёбой, экзаменами и чешским. Написать можно через Konnekt в Telegram.',
    h1: 'Репетиторы в Чехии',
    lead: 'Студенты и выпускники, которые помогают с учёбой. Написать можно через Konnekt.',
    emptyTitle: 'Скоро здесь появятся репетиторы',
    emptyText:
      'Помогаешь с учёбой? Создай анкету в Konnekt и включи «Страница на konnekt.cz».',
    become: 'Стать репетитором',
    from: 'от',
    formats: { online: 'Онлайн', offline: 'Вживую', both: 'Онлайн и вживую' },
    about: 'О себе',
    offers: 'Услуги',
    langs: 'Языки',
    write: 'Написать в Konnekt',
    writeNote: 'Сообщение уйдёт через Konnekt, ответ придёт в Telegram.',
    pageTitle: (name, what) => `${name}${what ? ` — ${what}` : ''} | Konnekt`,
    pageDescription: (name, what) => `${name}: ${what}. Написать можно через Konnekt.`,
    all: 'Все репетиторы',
  },
  uk: {
    section: 'Репетитори',
    title: 'Репетитори для студентів у Чехії — Konnekt',
    description:
      'Студенти й випускники чеських вишів допомагають з навчанням, іспитами та чеською. Написати можна через Konnekt у Telegram.',
    h1: 'Репетитори в Чехії',
    lead: 'Студенти й випускники, які допомагають з навчанням. Написати можна через Konnekt.',
    emptyTitle: 'Незабаром тут з’являться репетитори',
    emptyText:
      'Допомагаєш з навчанням? Створи анкету в Konnekt і увімкни «Сторінка на konnekt.cz».',
    become: 'Стати репетитором',
    from: 'від',
    formats: { online: 'Онлайн', offline: 'Наживо', both: 'Онлайн і наживо' },
    about: 'Про себе',
    offers: 'Послуги',
    langs: 'Мови',
    write: 'Написати в Konnekt',
    writeNote: 'Повідомлення піде через Konnekt, відповідь прийде в Telegram.',
    pageTitle: (name, what) => `${name}${what ? ` — ${what}` : ''} | Konnekt`,
    pageDescription: (name, what) => `${name}: ${what}. Написати можна через Konnekt.`,
    all: 'Усі репетитори',
  },
  cs: {
    section: 'Doučování',
    title: 'Doučovatelé pro studenty v Česku — Konnekt',
    description:
      'Studenti a absolventi českých vysokých škol pomáhají se studiem, zkouškami a češtinou. Napsat jim můžeš přes Konnekt v Telegramu.',
    h1: 'Doučovatelé v Česku',
    lead: 'Studenti a absolventi, kteří pomáhají se studiem. Napsat jim můžeš přes Konnekt.',
    emptyTitle: 'Brzy tu budou doučovatelé',
    emptyText:
      'Pomáháš se studiem? Vytvoř si profil v Konnektu a zapni „Stránka na konnekt.cz“.',
    become: 'Stát se doučovatelem',
    from: 'od',
    formats: { online: 'Online', offline: 'Osobně', both: 'Online i osobně' },
    about: 'O mně',
    offers: 'Služby',
    langs: 'Jazyky',
    write: 'Napsat v Konnektu',
    writeNote: 'Zpráva půjde přes Konnekt, odpověď přijde v Telegramu.',
    pageTitle: (name, what) => `${name}${what ? ` — ${what}` : ''} | Konnekt`,
    pageDescription: (name, what) => `${name}: ${what}. Napsat můžeš přes Konnekt.`,
    all: 'Všichni doučovatelé',
  },
  en: {
    section: 'Tutors',
    title: 'Tutors for students in Czechia — Konnekt',
    description:
      'Students and graduates of Czech universities help with studies, exams and Czech. Write to them through Konnekt in Telegram.',
    h1: 'Tutors in Czechia',
    lead: 'Students and graduates who help with studies. Write to them through Konnekt.',
    emptyTitle: 'Tutors will be here soon',
    emptyText:
      'Do you help with studies? Create a profile in Konnekt and turn on “Page on konnekt.cz”.',
    become: 'Become a tutor',
    from: 'from',
    formats: { online: 'Online', offline: 'In person', both: 'Online and in person' },
    about: 'About',
    offers: 'Services',
    langs: 'Languages',
    write: 'Write in Konnekt',
    writeNote: 'Your message goes through Konnekt; the answer comes in Telegram.',
    pageTitle: (name, what) => `${name}${what ? ` — ${what}` : ''} | Konnekt`,
    pageDescription: (name, what) => `${name}: ${what}. Write through Konnekt.`,
    all: 'All tutors',
  },
};
