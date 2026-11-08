/**
 * Where the card a link shows (og.ts) lives, and the tags that name it:
 * apart from the drawing so a page can name its card without loading what
 * draws it.
 */
import { type Lang, localePath } from '../paths.ts';

export const OG_WIDTH = 1200;
export const OG_HEIGHT = 630;

/** An article's card, next to its page: `/articles/<slug>/og.jpg`. */
export function cardPath(pagePath: string): string {
  return `${pagePath}og.jpg`;
}

/** The card of the articles' list in `lang`, which its rubrics and tags share too. */
export function listCardPath(lang: Lang): string {
  return localePath(lang, '/articles/og.jpg');
}

/** An og:image as Base.astro writes its tags. */
export interface OgImage {
  url: string;
  alt: string;
  width: number;
  height: number;
}

export function ogImage(path: string, site: string, alt: string): OgImage {
  return { url: new URL(path, site).href, alt, width: OG_WIDTH, height: OG_HEIGHT };
}
