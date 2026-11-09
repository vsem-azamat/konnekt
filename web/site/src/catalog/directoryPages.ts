/**
 * The directory's pages (directory.ts): a university's and a faculty's data,
 * or the response each answers instead. Apart from load.ts, which node's
 * tests import, because these read the texts through Astro's content layer.
 */

import type { CollectionEntry } from 'astro:content';

import type { PublicChat } from '../../../src/lib/chats.ts';
import { type Lang, localePath } from '../paths.ts';
import {
  type CatalogUniversity,
  mainChat,
  type UniversityChats,
  universitiesWithChats,
} from './catalog.ts';
import {
  ADDRESS,
  type FacultyCard,
  type FacultyChat,
  facultyChats,
  facultyList,
  movedFrom,
  placeIndexable,
  universityCode,
  universityLangs,
} from './directory.ts';
import { both } from './load.ts';
import { langOf, notFound, unavailable } from './page.ts';
import {
  facultyTexts,
  type PlaceText,
  placeArticles,
  placeText,
  textLangs,
} from './places.ts';

export interface UniversityProps {
  lang: Lang;
  university: CatalogUniversity;
  /** Its chats; null when the catalogue could not be read, and the page shows the way to the app instead. */
  chats: PublicChat[] | null;
  /** The other universities with chats in its city. */
  neighbours: UniversityChats[];
  text: PlaceText | null;
  faculties: FacultyCard[];
  articles: CollectionEntry<'articles'>[];
  indexable: boolean;
  /** The languages its page names as its versions: those search may keep. */
  langs: readonly Lang[];
}

/** A university the catalogue could not name, from its text. */
function fromText(code: string, text: PlaceText): CatalogUniversity {
  return {
    code,
    name: text.data.name,
    short_name: text.data.short ?? null,
    city: null,
    site_url: text.data.website,
    faculties: [],
  };
}

/** A permanent redirect from an old address, kept a day by Cloudflare. */
function moved(location: string): Response {
  return new Response(null, {
    status: 301,
    headers: { Location: location, 'Cache-Control': 'public, max-age=86400' },
  });
}

/**
 * The faculty cards of a university's page (directory.ts): the catalog's
 * faculties, by their catalog names, those with a text linking to it.
 * `known` is the university as the catalog lists it, if it could be read.
 */
async function facultyCards(
  lang: Lang,
  address: string,
  known: CatalogUniversity | undefined,
): Promise<FacultyCard[]> {
  const texts = (await facultyTexts(lang, address)).map(({ place, text }) => ({
    faculty: place.faculty as string,
    // Without the catalog's name: «FIT ЧВУТ — Факультет информационных
    // технологий», the tile says what follows the dash.
    name: text.data.name.split(' — ').at(-1) as string,
    short: text.data.short ?? (place.faculty as string).toUpperCase(),
    chats: text.data.chats.length,
  }));
  return facultyList(known?.code ?? '', known ? known.faculties : null, texts);
}

/**
 * A university's page: our text, when there is one, with the catalogue's
 * chats. Without the catalogue it still shows the text, and the way to
 * its chats in the app; without either it is no page.
 */
export async function universityPage(
  prefix: string | undefined,
  address: string | undefined,
): Promise<UniversityProps | Response> {
  const lang = langOf(prefix);
  if (!lang || !address) return notFound();
  const next = movedFrom(address);
  if (next) return moved(localePath(lang, `/universities/${next}/`));
  const code = universityCode(address);
  if (!code) return notFound();
  const [text, data] = await Promise.all([placeText(lang, address), both(lang)]);
  if (!data && !text) return unavailable(lang);
  const all = data ? universitiesWithChats(data.universities, data.chats) : [];
  const entry = all.find((u) => u.university.code === code);
  // A university with neither our text nor a chat has no page: nothing would be on it.
  if (data && !entry && !text) return notFound();
  const known = data?.universities.find((u) => u.code === code);
  const university = known ?? (text ? fromText(code, text) : null);
  if (!university) return notFound();
  const chats = data ? (entry?.chats ?? []) : null;
  const { city } = university;
  const place = { address, faculty: null };
  return {
    lang,
    university,
    chats,
    neighbours: all.filter(
      (u) => u !== entry && city !== null && u.university.city === city,
    ),
    text,
    faculties: await facultyCards(lang, address, known),
    articles: await placeArticles(lang, place),
    indexable: placeIndexable(text !== null, chats?.length ?? null),
    langs: universityLangs(lang, await textLangs(address), chats?.length ?? null),
  };
}

export interface FacultyProps {
  lang: Lang;
  university: CatalogUniversity;
  /** Its page's address under its university's (`fit`). */
  faculty: string;
  text: PlaceText;
  /** Its chats as its text names them; each a bare link when the catalogue could not be read. */
  chats: FacultyChat[];
  /** The university's main chat, below the faculty's own; null without the catalogue. */
  universityChat: PublicChat | null;
  /** The university's other faculties with a text. */
  siblings: FacultyCard[];
  articles: CollectionEntry<'articles'>[];
  /** The languages it has a text in, and so a page. */
  langs: Lang[];
}

/**
 * A faculty's page: only one with our text, the directory's own. Its chats
 * are the ones its text names, as the catalogue lists them when it can.
 */
export async function facultyPage(
  prefix: string | undefined,
  address: string | undefined,
  faculty: string | undefined,
): Promise<FacultyProps | Response> {
  const lang = langOf(prefix);
  if (!lang || !address || !faculty) return notFound();
  const next = movedFrom(address);
  if (next) return moved(localePath(lang, `/universities/${next}/${faculty}/`));
  const code = universityCode(address);
  if (!code || !ADDRESS.test(faculty)) return notFound();
  const text = await placeText(lang, `${address}/${faculty}`);
  if (!text) return notFound();
  const [own, data] = await Promise.all([placeText(lang, address), both(lang)]);
  const known = data?.universities.find((u) => u.code === code);
  const university =
    known ??
    (own
      ? fromText(code, own)
      : {
          code,
          name: address.toUpperCase(),
          short_name: null,
          city: null,
          site_url: null,
          faculties: [],
        });
  const theirs = data ? data.chats.filter((chat) => chat.institution === code) : null;
  return {
    lang,
    university,
    faculty,
    text,
    chats: facultyChats(text.data.chats, theirs),
    universityChat: theirs ? mainChat(theirs) : null,
    siblings: (await facultyCards(lang, address, known)).filter(
      (card) => card.faculty !== faculty,
    ),
    articles: await placeArticles(lang, { address: `${address}/${faculty}`, faculty }),
    langs: await textLangs(`${address}/${faculty}`),
  };
}
