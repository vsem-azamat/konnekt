/**
 * The directory's own words (directory.ts) on the university's and the
 * faculty's pages, in each language. The rest are the catalog's (texts.ts).
 */

import type { Lang } from '../paths.ts';

export interface DirectoryTexts {
  aboutUniversity: string;
  aboutFaculty: string;
  /** «Источники: …», before the list. */
  sources: string;
  /** «· проверено 9 ноября 2026», the latest any source was read. */
  checked: string;
  faculties: string;
  articlesAbout: (short: string) => string;
  /** Without the catalogue: the card that stands for the chats. */
  appTitle: (short: string) => string;
  appText: string;
  facultyChats: string;
  universityChat: (short: string) => string;
  otherFaculties: (short: string) => string;
  /** On an article: the universities and faculties it is about. */
  inArticle: string;
}

export const DIRECTORY_TEXTS: Record<Lang, DirectoryTexts> = {
  ru: {
    aboutUniversity: 'Коротко о вузе',
    aboutFaculty: 'О факультете',
    sources: 'Источники',
    checked: 'проверено',
    faculties: 'Факультеты',
    articlesAbout: (short) => `Статьи о ${short}`,
    appTitle: (short) => `Чаты ${short} в приложении`,
    appText: 'Список чатов сейчас не загрузился. В Konnekt они на месте.',
    facultyChats: 'Чаты факультета',
    universityChat: (short) => `Общий чат ${short}`,
    otherFaculties: (short) => `Другие факультеты ${short}`,
    inArticle: 'Вузы в статье',
  },
  uk: {
    aboutUniversity: 'Коротко про виш',
    aboutFaculty: 'Про факультет',
    sources: 'Джерела',
    checked: 'перевірено',
    faculties: 'Факультети',
    articlesAbout: (short) => `Статті про ${short}`,
    appTitle: (short) => `Чати ${short} у застосунку`,
    appText: 'Список чатів зараз не завантажився. У Konnekt вони на місці.',
    facultyChats: 'Чати факультету',
    universityChat: (short) => `Загальний чат ${short}`,
    otherFaculties: (short) => `Інші факультети ${short}`,
    inArticle: 'Виші у статті',
  },
  cs: {
    aboutUniversity: 'Stručně o škole',
    aboutFaculty: 'O fakultě',
    sources: 'Zdroje',
    checked: 'ověřeno',
    faculties: 'Fakulty',
    articlesAbout: (short) => `Články o ${short}`,
    appTitle: (short) => `Chaty ${short} v aplikaci`,
    appText: 'Seznam chatů se teď nenačetl. V Konnektu jsou na svém místě.',
    facultyChats: 'Chaty fakulty',
    universityChat: (short) => `Společný chat ${short}`,
    otherFaculties: (short) => `Další fakulty ${short}`,
    inArticle: 'Školy v článku',
  },
  en: {
    aboutUniversity: 'About the university',
    aboutFaculty: 'About the faculty',
    sources: 'Sources',
    checked: 'checked',
    faculties: 'Faculties',
    articlesAbout: (short) => `Articles about ${short}`,
    appTitle: (short) => `${short} chats in the app`,
    appText: 'The list of chats did not load just now. They are all in Konnekt.',
    facultyChats: 'Faculty chats',
    universityChat: (short) => `${short}’s main chat`,
    otherFaculties: (short) => `Other faculties of ${short}`,
    inArticle: 'Universities in this article',
  },
};
