interface OfferChipSource {
  subject?: string | null;
  institution?: string | null;
  service_type_name: string;
}

/**
 * What a chip on a helper's profile says about one offer. An offer without a
 * subject would show the university alone, which names no service; the service
 * takes the subject's place so the chip still says what is offered.
 */
export function offerChipText(offer: OfferChipSource): string {
  return [offer.subject ?? offer.service_type_name, offer.institution]
    .filter(Boolean)
    .join(' · ');
}
