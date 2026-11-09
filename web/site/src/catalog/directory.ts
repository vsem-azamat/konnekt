/**
 * The directory of universities and their faculties (Azamat's choice C,
 * agora 13358): our own text about each, in content/universities/, with the
 * catalogue's live chats mixed in.
 *
 * A page's address is the text's file name: content/universities/ru/cvut.md
 * is /universities/cvut/, ru/cvut/fit.md is /universities/cvut/fit/. The
 * catalog knows the same places by code (`cvut`, `cvut_fit`); the two agree
 * but for Charles University, whose code `uk` would read as Ukrainian in
 * /uk/universities/uk/, and which lives at its own domain's name instead.
 *
 * Pure functions, shared by the pages, the config and the tests.
 */

import type { PublicChat } from '../../../src/lib/chats.ts';
import { LANGS, type Lang, localePath } from '../paths.ts';
import { type CatalogFaculty, MIN_INDEXED_CHATS, mainChat } from './catalog.ts';

/** A university's address where it is not its catalog code. */
// A Map, not an object: `constructor` in a URL must not find Object.prototype's.
const ADDRESSES: ReadonlyMap<string, string> = new Map([['uk', 'cuni']]);
const CODES: ReadonlyMap<string, string> = new Map(
  [...ADDRESSES].map(([code, address]) => [address, code]),
);

/** A university's (or a faculty's) part of an address: lowercase latin and digits. */
export const ADDRESS = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** Where the catalog's university `code` lives on the site. */
export function universityAddress(code: string): string {
  return ADDRESSES.get(code) ?? code;
}

/**
 * The catalog code of the university at `address`, or null for an address
 * that is not one: an old one, which `movedFrom` answers, or no address at all.
 */
export function universityCode(address: string): string | null {
  if (!ADDRESS.test(address)) return null;
  const code = CODES.get(address);
  if (code) return code;
  return ADDRESSES.has(address) ? null : address;
}

/** The address a university had before it got its own, for its permanent redirect. */
export function movedFrom(address: string): string | null {
  return ADDRESSES.get(address) ?? null;
}

export function universityPath(lang: Lang, code: string): string {
  return localePath(lang, `/universities/${universityAddress(code)}/`);
}

/**
 * A faculty's address under its university's, from its catalog code:
 * `cvut_fit` is `fit`. Null for a code that is not the university's, or
 * leaves no address.
 */
export function facultyAddress(university: string, code: string): string | null {
  if (!code.startsWith(`${university}_`)) return null;
  const address = code.slice(university.length + 1).replace(/_/g, '-');
  return ADDRESS.test(address) ? address : null;
}

/** A faculty on its university's page: a card, which links to its page when it has one. */
export interface FacultyCard {
  /** Its page's address under its university's (`fit`). */
  faculty: string;
  name: string;
  short: string;
  /** How many chats its text names. */
  chats: number;
  /** Whether it has a page: a text of ours. */
  page: boolean;
}

/**
 * A university's faculties: every one the catalog lists, in its order and by
 * its names, those with a text of ours linking to their pages; then any text
 * for a faculty the catalog does not list. Without the catalog, the texts.
 */
export function facultyList(
  university: string,
  catalog: readonly CatalogFaculty[] | null,
  texts: readonly Omit<FacultyCard, 'page'>[],
): FacultyCard[] {
  const byAddress = new Map(texts.map((text) => [text.faculty, text]));
  const listed: FacultyCard[] = [];
  for (const faculty of catalog ?? []) {
    const address = facultyAddress(university, faculty.code);
    if (!address) continue;
    const text = byAddress.get(address);
    byAddress.delete(address);
    listed.push({
      faculty: address,
      name: faculty.name,
      short: faculty.short_name ?? text?.short ?? address.toUpperCase(),
      chats: text?.chats ?? 0,
      page: text !== undefined,
    });
  }
  return [...listed, ...[...byAddress.values()].map((text) => ({ ...text, page: true }))];
}

/** A university's page, or one of its faculties', from its text's address (`cvut`, `cvut/fit`). */
export function placePath(lang: Lang, address: string): string {
  return localePath(lang, `/universities/${address}/`);
}

/** Where a text lies: its language, its university's address, and its faculty's, if it is one. */
export interface TextPlace {
  lang: Lang;
  university: string;
  faculty: string | null;
  /** `cvut` or `cvut/fit`: what an article names it by. */
  address: string;
}

/** A text's place from its content id (`ru/cvut`, `ru/cvut/fit`); anything else stops the build. */
export function placeOf(id: string): TextPlace {
  const [lang, university, faculty, ...rest] = id.split('/');
  const ok =
    LANGS.includes(lang as Lang) &&
    university !== undefined &&
    ADDRESS.test(university) &&
    (faculty === undefined || ADDRESS.test(faculty)) &&
    rest.length === 0;
  if (!ok) {
    throw new Error(
      `universities/${id}: expected <lang>/<university>.md or <lang>/<university>/<faculty>.md, lowercase latin`,
    );
  }
  if (movedFrom(university as string)) {
    throw new Error(
      `universities/${id}: ${university} lives at ${movedFrom(university as string)}`,
    );
  }
  return {
    lang: lang as Lang,
    university: university as string,
    faculty: faculty ?? null,
    address: faculty ? `${university}/${faculty}` : (university as string),
  };
}

/**
 * Whether a university's or a faculty's page goes to search: when it has our
 * text. A university without one still does on its chats alone, as before
 * the directory, rather than leave search while its text is being written.
 */
export function placeIndexable(hasText: boolean, chats: number | null): boolean {
  return hasText || (chats ?? 0) >= MIN_INDEXED_CHATS;
}

/**
 * The languages a university's page in `lang` names as its versions
 * (hreflang, the language switcher): only those search may keep. With
 * enough chats it is in every language; otherwise in its text's languages.
 * A page that is itself not kept names every language, as before.
 */
export function universityLangs(
  lang: Lang,
  textLangs: readonly Lang[],
  chats: number | null,
): readonly Lang[] {
  if ((chats ?? 0) >= MIN_INDEXED_CHATS) return LANGS;
  return textLangs.includes(lang) ? textLangs : LANGS;
}

/**
 * What an article names a page by, checked against the texts there are: an
 * article in a language may only name a page with a text in it, so its link
 * never leads to a page that does not exist. A published article names only
 * published texts; a draft may name a draft. `texts` maps the content ids to
 * whether each is a draft.
 */
export function checkPlaces(
  article: { id: string; draft?: boolean; universities?: readonly string[] },
  texts: ReadonlyMap<string, boolean>,
): void {
  const lang = article.id.split('/')[0];
  for (const address of article.universities ?? []) {
    const draft = texts.get(`${lang}/${address}`);
    if (draft === undefined) {
      throw new Error(
        `article ${article.id}: universities names ${address}, and there is no content/universities/${lang}/${address}.md`,
      );
    }
    if (draft && !article.draft) {
      throw new Error(
        `article ${article.id}: universities names ${address}, whose text is still a draft`,
      );
    }
  }
}

/**
 * The articles about a place, by what they name: a university's are those
 * naming it or any of its faculties, a faculty's those naming it.
 */
export function articlesAbout<T extends { universities?: readonly string[] }>(
  articles: readonly T[],
  place: Pick<TextPlace, 'address' | 'faculty'>,
): T[] {
  return articles.filter((article) =>
    (article.universities ?? []).some(
      (named) =>
        named === place.address ||
        (place.faculty === null && named.startsWith(`${place.address}/`)),
    ),
  );
}

/** A chat link as written in a text or by the catalogue, for comparing the two. */
function sameLink(link: string): string {
  return link
    .trim()
    .toLowerCase()
    .replace(/^http:\/\//, 'https://')
    .replace(/^https:\/\/(?:telegram\.me|telegram\.dog)\//, 'https://t.me/')
    .replace(/\/+$/, '');
}

/** A faculty's chat: as the catalogue lists it, or only its link when it does not (or is not there). */
export type FacultyChat = { chat: PublicChat } | { link: string };

/**
 * A faculty's chats, by the links its text names: the catalogue's chats carry
 * their university and not their faculty. In the text's order; a link the
 * catalogue does not list stays a link. Each chat once: a link named twice,
 * however written, is one row, and the university's main chat, which the
 * page shows as its own row with a note, is not repeated among them.
 */
export function facultyChats(
  links: readonly string[],
  chats: readonly PublicChat[] | null,
): { chats: FacultyChat[]; universityChat: PublicChat | null } {
  const byLink = new Map((chats ?? []).map((chat) => [sameLink(chat.link), chat]));
  const universityChat = chats ? mainChat(chats) : null;
  const seen = new Set(universityChat ? [sameLink(universityChat.link)] : []);
  const own: FacultyChat[] = [];
  for (const link of links) {
    const key = sameLink(link);
    if (seen.has(key)) continue;
    seen.add(key);
    const chat = byLink.get(key);
    own.push(chat ? { chat } : { link });
  }
  return { chats: own, universityChat };
}
