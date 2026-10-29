/**
 * What «Мои услуги» sends back when one service changes.
 *
 * The server takes the whole list or none of it (`HelperUpsert.offers` is
 * authoritative), so changing one price is a save of every offer with that
 * one different.
 */

import type { MyHelper, MyOffer, OfferInput, PriceUnit } from './types';

/**
 * An offer as it was read, ready to be saved again.
 *
 * Without `paused`: the server keeps the pause of an offer that does not say,
 * and only the switch, which has its own endpoint, should ever change it.
 */
export function asInput(offer: MyOffer): OfferInput {
  return {
    service_type_id: offer.service_type_id,
    subject_id: offer.subject_id,
    institution_id: offer.institution_id,
    price_amount: offer.price_amount,
    price_unit: offer.price_unit,
    langs: offer.langs,
    option_ids: offer.option_ids,
    note: offer.note,
    turnaround_days: offer.turnaround_days,
  };
}

/** Every offer, with the one `id` repriced, or dropped when `price` is null. */
export function offersWith(
  offers: MyOffer[],
  id: number,
  price: { price_amount: number | null; price_unit: PriceUnit } | null,
): OfferInput[] {
  return offers.flatMap((offer) => {
    if (offer.id !== id) return [asInput(offer)];
    return price ? [{ ...asInput(offer), ...price }] : [];
  });
}

/**
 * The `publish` that leaves the profile where it is.
 *
 * Not optional on the server: a save without it reads as «hide», so a price
 * fixed on a listed profile would take the profile out of the catalog.
 */
export function keepsListed(helper: MyHelper): boolean {
  return helper.status === 'published' || helper.status === 'banned';
}

/** The profile with one switch flipped, for the screen before the server answers. */
export function withPaused(helper: MyHelper, id: number, paused: boolean): MyHelper {
  return {
    ...helper,
    offers: helper.offers.map((offer) =>
      offer.id === id ? { ...offer, paused } : offer,
    ),
  };
}

/**
 * Every service switched off: the profile is listed, and in no list or search,
 * which filter on the service rather than the profile.
 */
export function allPaused(helper: MyHelper): boolean {
  return helper.offers.length > 0 && helper.offers.every((offer) => offer.paused);
}

/** The services students can find: the switched-off ones are kept, not shown. */
export function liveCount(helper: MyHelper): number {
  return helper.offers.filter((offer) => !offer.paused).length;
}

/** One thing a listed profile is missing, in the order «Что добавить» asks. */
export type Missing = 'subject' | 'price' | 'headline';

/**
 * What a published profile still lacks, for the card on «Мои услуги».
 *
 * Publishing asks for nothing, so a profile can be listed as a name alone,
 * and in the results that reads as a broken card. Asked only of live offers:
 * a paused one is not in the catalog to look empty. A subject only where the
 * service takes one (`requiresSubject`, by service type id); «договорная» is
 * an answer to the price, not a missing one.
 */
export function whatToAdd(helper: MyHelper, requiresSubject: Set<number>): Missing[] {
  const live = helper.offers.filter((offer) => !offer.paused);
  const missing: Missing[] = [];
  if (
    live.some(
      (offer) => requiresSubject.has(offer.service_type_id) && offer.subject_id === null,
    )
  ) {
    missing.push('subject');
  }
  if (
    live.some((offer) => offer.price_amount === null && offer.price_unit !== 'negotiable')
  ) {
    missing.push('price');
  }
  if (!helper.headline) missing.push('headline');
  return missing;
}
