/**
 * Each catalog page's data, or the response it answers instead: the same for
 * the Russian page at the root and for its prefixed translations, so each
 * page file only renders.
 */

import type { PublicChat } from '../../../src/lib/chats.ts';
import type { Lang } from '../paths.ts';
import {
  type CatalogUniversity,
  type Catalogue,
  catalogue,
  cities,
  cityFromSlug,
  type UniversityChats,
  universitiesWithChats,
} from './catalog.ts';
import { langOf, notFound, unavailable } from './page.ts';
import { publicChats, tutor, tutors, universities } from './source.ts';
import { idFromSlug, type TutorCard, type TutorPage, tutorPath } from './tutors.ts';

async function both(
  lang: Lang,
): Promise<{ chats: PublicChat[]; universities: CatalogUniversity[] } | null> {
  try {
    const [chats, list] = await Promise.all([publicChats(), universities(lang)]);
    return { chats, universities: list };
  } catch (error) {
    console.error('catalog pages: no data to render', error);
    return null;
  }
}

export interface UniversitiesProps {
  lang: Lang;
  list: UniversityChats[];
  cities: string[];
  /** The city `?city=` picked, or null: a filtered page is noindex. */
  city: string | null;
  filtered: boolean;
  /** The chats /chats/ lists under subjects, work and general: no university's. */
  loose: number;
}

export async function universitiesPage(
  prefix: string | undefined,
  url: URL,
): Promise<UniversitiesProps | Response> {
  const lang = langOf(prefix);
  if (!lang) return notFound();
  const data = await both(lang);
  if (!data) return unavailable(lang);
  const all = universitiesWithChats(data.universities, data.chats);
  const choices = [
    ...new Set(all.map((u) => u.university.city).filter((c) => c !== null)),
  ];
  const city = cityFromSlug(url.searchParams.get('city'), choices);
  return {
    lang,
    list: city ? all.filter((u) => u.university.city === city) : all,
    cities: choices,
    city,
    filtered: url.search !== '',
    loose: catalogue(data.chats, data.universities).topics.reduce(
      (sum, { chats }) => sum + chats.length,
      0,
    ),
  };
}

export interface UniversityProps {
  lang: Lang;
  entry: UniversityChats;
  /** The other universities with chats in its city. */
  neighbours: UniversityChats[];
}

export async function universityPage(
  prefix: string | undefined,
  code: string | undefined,
): Promise<UniversityProps | Response> {
  const lang = langOf(prefix);
  if (!lang) return notFound();
  const data = await both(lang);
  if (!data) return unavailable(lang);
  const all = universitiesWithChats(data.universities, data.chats);
  // A university with no chat has no page: nothing would be on it.
  const entry = all.find((u) => u.university.code === code);
  if (!entry) return notFound();
  const { city } = entry.university;
  return {
    lang,
    entry,
    neighbours: all.filter(
      (u) => u !== entry && city !== null && u.university.city === city,
    ),
  };
}

export interface ChatsProps {
  lang: Lang;
  catalogue: Catalogue;
  cities: string[];
  city: string | null;
  filtered: boolean;
  total: number;
}

export async function chatsPage(
  prefix: string | undefined,
  url: URL,
): Promise<ChatsProps | Response> {
  const lang = langOf(prefix);
  if (!lang) return notFound();
  const data = await both(lang);
  if (!data) return unavailable(lang);
  const choices = cities(data.chats);
  const city = cityFromSlug(url.searchParams.get('city'), choices);
  return {
    lang,
    catalogue: catalogue(data.chats, data.universities, city),
    cities: choices,
    city,
    filtered: url.search !== '',
    total: data.chats.length,
  };
}

export interface TutorsProps {
  lang: Lang;
  list: TutorCard[];
}

export async function tutorsPage(
  prefix: string | undefined,
): Promise<TutorsProps | Response> {
  const lang = langOf(prefix);
  if (!lang) return notFound();
  try {
    return { lang, list: await tutors(lang) };
  } catch (error) {
    console.error('tutors page: no data to render', error);
    return unavailable(lang);
  }
}

export interface TutorProps {
  lang: Lang;
  tutor: TutorPage;
}

/**
 * A tutor's page by the id its slug ends with. A slug whose name part is not
 * the catalog's (an old one, after a change of name) is sent to the current
 * one for good: the id is the same person.
 */
export async function tutorPage(
  prefix: string | undefined,
  slug: string | undefined,
): Promise<TutorProps | Response> {
  const lang = langOf(prefix);
  const id = idFromSlug(slug);
  if (!lang || id === null) return notFound();
  let page: TutorPage | null;
  try {
    page = await tutor(lang, id);
  } catch (error) {
    console.error('tutor page: no data to render', error);
    return unavailable(lang);
  }
  if (!page) return notFound();
  if (page.slug !== slug)
    return new Response(null, {
      status: 301,
      headers: {
        Location: tutorPath(lang, page.slug),
        'Cache-Control': 'public, max-age=3600',
      },
    });
  return { lang, tutor: page };
}
