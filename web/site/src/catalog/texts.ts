/**
 * The catalog pages' own words in each language. Universities, chats and
 * cities keep their names: those are names, not text.
 */

import type { Topic } from '../../../src/lib/chats.ts';
import { num } from '../landing/copy.ts';
import type { Lang } from '../paths.ts';

/** A noun's forms by Intl.PluralRules category; `other` stands for any it lacks. */
type Forms = Partial<Record<Intl.LDMLPluralRule, string>> & { other: string };

export interface CatalogTexts {
  home: string;
  nav: string;
  cityNav: string;
  allCities: string;
  all: string;
  chats: Forms;
  members: Forms;
  subscribers: Forms;
  channel: string;
  forum: string;
  external: string;
  main: string;
  allCzechia: string;
  /** A university's page: its headings, which are the app's but for the first. */
  pageTopics: Record<Topic, string>;
  /** /chats/: the app's headings. */
  topics: Record<Topic, string>;
  open: string;
  free: string;
  freeFaculty: string;
  inCatalog: string;
  inMain: string;
  thinTitle: string;
  thinText: (short: string) => string;
  suggest: string;
  neighbours: (city: string) => string;
  moreUniversities: string;
  more: (chats: string, short: string) => string;
  search: string;
  searchPlaceholder: string;
  empty: string;
  emptyLink: string;
  note: string;
  looseCard: string;
  looseText: (chats: string) => string;
  universitiesTitle: string;
  universitiesDescription: string;
  universitiesH1: string;
  universitiesLead: (n: number) => string;
  universityTitle: (short: string) => string;
  universityDescription: (chats: string, short: string, name: string) => string;
  universityH1: (short: string) => string;
  chatsTitle: string;
  chatsDescription: (chats: string) => string;
  chatsH1: string;
  chatsLead: (chats: string) => string;
  unavailable: string;
}

export const CATALOG_TEXTS: Record<Lang, CatalogTexts> = {
  ru: {
    home: 'Konnekt',
    nav: 'Навигация',
    cityNav: 'Город',
    allCities: 'Все города',
    all: 'Все',
    chats: { one: 'чат', few: 'чата', many: 'чатов', other: 'чата' },
    members: {
      one: 'участник',
      few: 'участника',
      many: 'участников',
      other: 'участника',
    },
    subscribers: {
      one: 'подписчик',
      few: 'подписчика',
      many: 'подписчиков',
      other: 'подписчика',
    },
    channel: 'канал',
    forum: 'с темами',
    external: 'не наш чат',
    main: 'главный чат',
    allCzechia: 'Вся Чехия',
    pageTopics: {
      university: 'Вуз и факультеты',
      subjects: 'Предметы',
      dorms: 'Общежития',
      work_it: 'Работа и IT',
      general: 'Общее',
    },
    topics: {
      university: 'Вузы',
      subjects: 'Предметы',
      dorms: 'Общежития',
      work_it: 'Работа и IT',
      general: 'Общее',
    },
    open: 'Открыть в Konnekt',
    free: 'Бесплатно, в Telegram.',
    freeFaculty: 'Бесплатно, в Telegram. Покажем чаты твоего факультета.',
    inCatalog: 'в каталоге',
    inMain: 'в главном чате',
    thinTitle: 'Здесь пока один чат',
    thinText: (short) =>
      `Знаешь чат факультета или общежития ${short}? Предложи его в Konnekt, и он появится на этой странице.`,
    suggest: 'Предложить чат',
    neighbours: (city) => `Другие вузы: ${city}`,
    moreUniversities: 'Ещё вузы',
    more: (chats, short) => `Ещё ${chats} ${short}`,
    search: 'Найти чат',
    searchPlaceholder: 'Вуз, факультет, общежитие…',
    empty: 'Такого чата пока нет. Предложи его в',
    emptyLink: 'Konnekt',
    note: 'Число участников — последний замер бота; у чата без замера числа нет.',
    looseCard: 'Чаты без вуза',
    looseText: (chats) => `Предметы, работа, общее: ещё ${chats} в общем каталоге.`,
    universitiesTitle: 'Вузы Чехии: чаты студентов по университетам | Konnekt',
    universitiesDescription:
      'Чаты студентов вузов Чехии в Telegram: общие, факультеты и общежития. Каталог Konnekt.',
    universitiesH1: 'Вузы Чехии и их чаты',
    universitiesLead: (n) =>
      `Общие чаты, факультеты и общежития: ${num('ru', n)} вузов. Выбери свой и посмотри, где уже сидят однокурсники.`,
    universityTitle: (short) =>
      `Чаты ${short}: факультеты и общежития в Telegram | Konnekt`,
    universityDescription: (chats, short, name) =>
      `${chats} студентов ${short} (${name}) в Telegram: общие, факультеты, общежития. Каталог Konnekt.`,
    universityH1: (short) => `Чаты ${short}`,
    chatsTitle: 'Студенческие чаты Чехии в Telegram | Konnekt',
    chatsDescription: (chats) =>
      `${chats} студентов в Чехии: вузы, факультеты, общежития, предметы и работа. Каталог Konnekt.`,
    chatsH1: 'Студенческие чаты Чехии',
    chatsLead: (chats) =>
      `${chats}: вузы и факультеты, общежития, предметы и работа. Нажми на чат, чтобы открыть его в Telegram.`,
    unavailable: 'Каталог сейчас не открывается. Попробуй через минуту.',
  },
  uk: {
    home: 'Konnekt',
    nav: 'Навігація',
    cityNav: 'Місто',
    allCities: 'Усі міста',
    all: 'Усі',
    chats: { one: 'чат', few: 'чати', many: 'чатів', other: 'чату' },
    members: { one: 'учасник', few: 'учасники', many: 'учасників', other: 'учасника' },
    subscribers: {
      one: 'підписник',
      few: 'підписники',
      many: 'підписників',
      other: 'підписника',
    },
    channel: 'канал',
    forum: 'з темами',
    external: 'не наш чат',
    main: 'головний чат',
    allCzechia: 'Уся Чехія',
    pageTopics: {
      university: 'Виш і факультети',
      subjects: 'Предмети',
      dorms: 'Гуртожитки',
      work_it: 'Робота та IT',
      general: 'Загальне',
    },
    topics: {
      university: 'Виші',
      subjects: 'Предмети',
      dorms: 'Гуртожитки',
      work_it: 'Робота та IT',
      general: 'Загальне',
    },
    open: 'Відкрити в Konnekt',
    free: 'Безкоштовно, у Telegram.',
    freeFaculty: 'Безкоштовно, у Telegram. Покажемо чати твого факультету.',
    inCatalog: 'у каталозі',
    inMain: 'у головному чаті',
    thinTitle: 'Тут поки один чат',
    thinText: (short) =>
      `Знаєш чат факультету чи гуртожитку ${short}? Запропонуй його в Konnekt, і він з’явиться на цій сторінці.`,
    suggest: 'Запропонувати чат',
    neighbours: (city) => `Інші виші: ${city}`,
    moreUniversities: 'Ще виші',
    more: (chats, short) => `Ще ${chats} ${short}`,
    search: 'Знайти чат',
    searchPlaceholder: 'Виш, факультет, гуртожиток…',
    empty: 'Такого чату поки немає. Запропонуй його в',
    emptyLink: 'Konnekt',
    note: 'Кількість учасників — останній замір бота; у чату без заміру числа немає.',
    looseCard: 'Чати без вишу',
    looseText: (chats) =>
      `Предмети, робота, загальне: ще ${chats} у загальному каталозі.`,
    universitiesTitle: 'Виші Чехії: чати студентів за університетами | Konnekt',
    universitiesDescription:
      'Чати студентів вишів Чехії в Telegram: загальні, факультети й гуртожитки. Каталог Konnekt.',
    universitiesH1: 'Виші Чехії та їхні чати',
    universitiesLead: (n) =>
      `Загальні чати, факультети й гуртожитки: ${num('uk', n)} вишів. Обери свій і подивись, де вже сидять одногрупники.`,
    universityTitle: (short) =>
      `Чати ${short}: факультети й гуртожитки в Telegram | Konnekt`,
    universityDescription: (chats, short, name) =>
      `${chats} студентів ${short} (${name}) у Telegram: загальні, факультети, гуртожитки. Каталог Konnekt.`,
    universityH1: (short) => `Чати ${short}`,
    chatsTitle: 'Студентські чати Чехії в Telegram | Konnekt',
    chatsDescription: (chats) =>
      `${chats} студентів у Чехії: виші, факультети, гуртожитки, предмети й робота. Каталог Konnekt.`,
    chatsH1: 'Студентські чати Чехії',
    chatsLead: (chats) =>
      `${chats}: виші й факультети, гуртожитки, предмети й робота. Натисни на чат, щоб відкрити його в Telegram.`,
    unavailable: 'Каталог зараз не відкривається. Спробуй за хвилину.',
  },
  cs: {
    home: 'Konnekt',
    nav: 'Navigace',
    cityNav: 'Město',
    allCities: 'Všechna města',
    all: 'Vše',
    chats: { one: 'chat', few: 'chaty', many: 'chatu', other: 'chatů' },
    members: { one: 'člen', few: 'členové', many: 'člena', other: 'členů' },
    subscribers: {
      one: 'odběratel',
      few: 'odběratelé',
      many: 'odběratele',
      other: 'odběratelů',
    },
    channel: 'kanál',
    forum: 's tématy',
    external: 'není náš chat',
    main: 'hlavní chat',
    allCzechia: 'Celé Česko',
    pageTopics: {
      university: 'Škola a fakulty',
      subjects: 'Předměty',
      dorms: 'Koleje',
      work_it: 'Práce a IT',
      general: 'Obecné',
    },
    topics: {
      university: 'Vysoké školy',
      subjects: 'Předměty',
      dorms: 'Koleje',
      work_it: 'Práce a IT',
      general: 'Obecné',
    },
    open: 'Otevřít v Konnektu',
    free: 'Zdarma, v Telegramu.',
    freeFaculty: 'Zdarma, v Telegramu. Ukážeme chaty tvé fakulty.',
    inCatalog: 'v katalogu',
    inMain: 'v hlavním chatu',
    thinTitle: 'Zatím je tu jeden chat',
    thinText: (short) =>
      `Znáš chat fakulty nebo koleje ${short}? Navrhni ho v Konnektu a objeví se na této stránce.`,
    suggest: 'Navrhnout chat',
    neighbours: (city) => `Další školy: ${city}`,
    moreUniversities: 'Další školy',
    more: (chats, short) => `Další ${chats} ${short}`,
    search: 'Najít chat',
    searchPlaceholder: 'Škola, fakulta, kolej…',
    empty: 'Takový chat tu zatím není. Navrhni ho v',
    emptyLink: 'Konnektu',
    note: 'Počet členů je poslední měření bota; chat bez měření číslo nemá.',
    looseCard: 'Chaty mimo školy',
    looseText: (chats) => `Předměty, práce, obecné: dalších ${chats} v celém katalogu.`,
    universitiesTitle: 'Vysoké školy v Česku: studentské chaty podle univerzit | Konnekt',
    universitiesDescription:
      'Studentské chaty českých vysokých škol v Telegramu: obecné, fakulty a koleje. Katalog Konnekt.',
    universitiesH1: 'Vysoké školy a jejich chaty',
    universitiesLead: (n) =>
      `Obecné chaty, fakulty a koleje ${num('cs', n)} vysokých škol. Vyber tu svou a podívej se, kde už jsou spolužáci.`,
    universityTitle: (short) => `Chaty ${short}: fakulty a koleje v Telegramu | Konnekt`,
    universityDescription: (chats, short, name) =>
      `${chats} studentů ${short} (${name}) v Telegramu: obecné, fakulty, koleje. Katalog Konnekt.`,
    universityH1: (short) => `Chaty ${short}`,
    chatsTitle: 'Studentské chaty v Česku na Telegramu | Konnekt',
    chatsDescription: (chats) =>
      `${chats} studentů v Česku: vysoké školy, fakulty, koleje, předměty a práce. Katalog Konnekt.`,
    chatsH1: 'Studentské chaty v Česku',
    chatsLead: (chats) =>
      `${chats}: školy a fakulty, koleje, předměty a práce. Klepni na chat a otevře se v Telegramu.`,
    unavailable: 'Katalog se teď nenačetl. Zkus to za minutu.',
  },
  en: {
    home: 'Konnekt',
    nav: 'Breadcrumbs',
    cityNav: 'City',
    allCities: 'All cities',
    all: 'All',
    chats: { one: 'chat', other: 'chats' },
    members: { one: 'member', other: 'members' },
    subscribers: { one: 'subscriber', other: 'subscribers' },
    channel: 'channel',
    forum: 'with topics',
    external: 'not run by us',
    main: 'main chat',
    allCzechia: 'All of Czechia',
    pageTopics: {
      university: 'University and faculties',
      subjects: 'Subjects',
      dorms: 'Dorms',
      work_it: 'Work and IT',
      general: 'General',
    },
    topics: {
      university: 'Universities',
      subjects: 'Subjects',
      dorms: 'Dorms',
      work_it: 'Work and IT',
      general: 'General',
    },
    open: 'Open in Konnekt',
    free: 'Free, in Telegram.',
    freeFaculty: 'Free, in Telegram. We’ll show your faculty’s chats.',
    inCatalog: 'in the catalog',
    inMain: 'in the main chat',
    thinTitle: 'Just one chat so far',
    thinText: (short) =>
      `Know a ${short} faculty or dorm chat? Suggest it in Konnekt and it will appear on this page.`,
    suggest: 'Suggest a chat',
    neighbours: (city) => `Other universities: ${city}`,
    moreUniversities: 'More universities',
    more: (chats, short) => `${chats} more at ${short}`,
    search: 'Find a chat',
    searchPlaceholder: 'University, faculty, dorm…',
    empty: 'No such chat yet. Suggest it in',
    emptyLink: 'Konnekt',
    note: 'Member counts are the bot’s latest; a chat never counted shows no number.',
    looseCard: 'Chats outside universities',
    looseText: (chats) => `Subjects, work, general: ${chats} more in the whole catalog.`,
    universitiesTitle: 'Czech universities: student chats by university | Konnekt',
    universitiesDescription:
      'Telegram chats of students at Czech universities: general, faculties and dorms. The Konnekt catalog.',
    universitiesH1: 'Czech universities and their chats',
    universitiesLead: (n) =>
      `General chats, faculties and dorms of ${num('en', n)} universities. Pick yours and see where your classmates already are.`,
    universityTitle: (short) =>
      `${short} chats: faculties and dorms on Telegram | Konnekt`,
    universityDescription: (chats, short, name) =>
      `${chats} of ${short} (${name}) students on Telegram: general, faculties, dorms. The Konnekt catalog.`,
    universityH1: (short) => `${short} chats`,
    chatsTitle: 'Student chats in Czechia on Telegram | Konnekt',
    chatsDescription: (chats) =>
      `${chats} for students in Czechia: universities, faculties, dorms, subjects and work. The Konnekt catalog.`,
    chatsH1: 'Student chats in Czechia',
    chatsLead: (chats) =>
      `${chats}: universities and faculties, dorms, subjects and work. Tap a chat to open it in Telegram.`,
    unavailable: 'The catalog didn’t load just now. Try again in a minute.',
  },
};

/** The noun's form for `n` in `lang`: чат, чата, чатов. */
export function noun(lang: Lang, n: number, forms: Forms): string {
  return forms[new Intl.PluralRules(lang).select(n)] ?? forms.other;
}

/** `n` with its noun in `lang`: 1 чат, 2 чата, 5 чатов; 1 chat, 5 chats. */
export function count(lang: Lang, n: number, forms: Forms): string {
  return `${num(lang, n)} ${noun(lang, n, forms)}`;
}
