/**
 * A real photo's credit, as its licence asks (CC BY and the like): who took
 * it, under which licence, whether part of it was cut away, and where it
 * came from. One line wherever a photo is shown: an article's cover, a
 * directory page's, and a photo in a directory text (catalog/blocks.ts).
 */

import type { Lang } from '../paths.ts';
import { TEXTS } from '../texts.ts';

export interface Credit {
  author: string;
  licence: string;
  /** The licence's own text, which CC licences ask a credit to link. */
  licenceUrl?: string | undefined;
  source: string;
  /** Whether part of the photo was cut away, which CC BY asks a credit to say. */
  cropped: boolean;
}

/** A piece of the line: plain text, or a link. */
export interface CreditPart {
  text: string;
  href?: string;
}

/** Where the photo is from as a reader knows it: «Wikimedia Commons» rather than its host name. */
export function creditSite(source: string): string {
  const host = new URL(source).hostname;
  return host === 'commons.wikimedia.org'
    ? 'Wikimedia Commons'
    : host.replace(/^www\./, '');
}

/** «Фото: Utar, CC BY-SA 3.0, кадрировано, Wikimedia Commons», the licence and the site linked. */
export function creditLine(lang: Lang, credit: Credit): CreditPart[] {
  const t = TEXTS[lang];
  return [
    { text: `${t.photo}: ${credit.author}, ` },
    credit.licenceUrl
      ? { text: credit.licence, href: credit.licenceUrl }
      : { text: credit.licence },
    { text: credit.cropped ? `, ${t.cropped}, ` : ', ' },
    { text: creditSite(credit.source), href: credit.source },
  ];
}
