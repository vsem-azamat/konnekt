/**
 * The directory's texts as the pages read them (directory.ts): which there
 * are in a language, and the published articles that name them.
 */

import { type CollectionEntry, getCollection } from 'astro:content';

import { LANGS, type Lang } from '../paths.ts';
import { articlesAbout, placeOf, type TextPlace } from './directory.ts';

export type PlaceText = CollectionEntry<'universities'>;

/** A draft is the dev server's only: the public page stays as it was until the text is checked. */
const shown = (text: PlaceText) => !text.data.draft || import.meta.env.DEV;

let read: Promise<PlaceText[]> | undefined;

/**
 * Every text to show, read once per server: the built collection never
 * changes, and Astro warns on each empty read or missing entry, which would
 * be every request while there are few texts. The dev server reads anew, as
 * its texts are being edited.
 */
function texts(): Promise<PlaceText[]> {
  if (import.meta.env.DEV) return getCollection('universities', shown);
  read ??= getCollection('universities', shown);
  return read;
}

/** The text at `address` (`cvut`, `cvut/fit`) in `lang`, if there is one to show. */
export async function placeText(lang: Lang, address: string): Promise<PlaceText | null> {
  const id = `${lang}/${address}`;
  return (await texts()).find((text) => text.id === id) ?? null;
}

/** The faculties of the university at `address` that have a text in `lang`, in their files' order. */
export async function facultyTexts(
  lang: Lang,
  address: string,
): Promise<{ place: TextPlace; text: PlaceText }[]> {
  return (await texts())
    .map((text) => ({ place: placeOf(text.id), text }))
    .filter(
      ({ place }) =>
        place.lang === lang && place.university === address && place.faculty !== null,
    );
}

/** The published articles in `lang` about the place, newest first. */
export async function placeArticles(
  lang: Lang,
  place: Pick<TextPlace, 'address' | 'faculty'>,
): Promise<CollectionEntry<'articles'>[]> {
  const mine = (await getCollection('articles'))
    .filter((article) => !article.data.draft && article.id.startsWith(`${lang}/`))
    .map((article) => ({ article, universities: article.data.universities }));
  return articlesAbout(mine, place)
    .map(({ article }) => article)
    .sort((a, b) => b.data.published.valueOf() - a.data.published.valueOf());
}

/** Every text there is to show, with its place: the sitemap's. */
export async function allPlaceTexts(): Promise<{ place: TextPlace; text: PlaceText }[]> {
  return (await texts()).map((text) => ({
    place: placeOf(text.id),
    text,
  }));
}

/** The languages the text at `address` is in: a faculty's page exists in those alone. */
export async function textLangs(address: string): Promise<Lang[]> {
  const langs = (await allPlaceTexts())
    .filter(({ place }) => place.address === address)
    .map(({ place }) => place.lang);
  return LANGS.filter((lang) => langs.includes(lang));
}
