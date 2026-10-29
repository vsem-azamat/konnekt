/**
 * What the «Документы и жизнь» shelf draws, given the paid places.
 *
 * A place with a live card draws the card. A free place invites a partner
 * (E1), but only when somebody is there to answer (`ADS_CONTACT`): an
 * invitation to write to nobody is a dead end, so without a contact a free
 * place is the plain row of its service. With no card and no contact there is
 * nothing to draw, and the shelf stays today's tiles. See
 * catalog/docs/showcase-api.md.
 */

import type { HomeSection, ShowcaseCard, ShowcaseSlot } from './types';

export type Place =
  | { kind: 'card'; card: ShowcaseCard; section: HomeSection | undefined }
  | { kind: 'open'; section: HomeSection };

export interface Shelf {
  /** The places drawn as cards, in order: the first is the big one. */
  places: Place[];
  /** The shelf's other services, and the free places with nobody to answer. */
  rows: HomeSection[];
}

export function shelf(
  slots: ShowcaseSlot[],
  life: HomeSection[],
  contact: string | null | undefined,
): Shelf | null {
  const byCode = new Map(life.map((section) => [section.code, section]));
  const places: Place[] = [];
  const inPlaces = new Set<string>();
  for (const slot of slots) {
    const section = byCode.get(slot.service);
    if (slot.card) {
      places.push({ kind: 'card', card: slot.card, section });
      inPlaces.add(slot.service);
    } else if (contact && section) {
      places.push({ kind: 'open', section });
      inPlaces.add(slot.service);
    }
  }
  if (!places.some((place) => place.kind === 'card') && !contact) return null;
  return { places, rows: life.filter((section) => !inPlaces.has(section.code)) };
}

/** «от 1 290 Kč», with the locale's grouping and a space that does not break. */
export function priceFrom(amount: number | null, locale: string): string | null {
  if (amount === null) return null;
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 })
    .format(amount)
    .replace(/\s/g, ' ');
}

/** The @username a t.me contact link names, for «Откроется чат с @…». */
export function handleOf(link: string): string | null {
  const match = /^https:\/\/t\.me\/([A-Za-z0-9_]+)\/?$/.exec(link);
  return match ? `@${match[1]}` : null;
}
