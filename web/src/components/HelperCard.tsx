import { Trans } from '@lingui/react/macro';

import { PhraseView, PriceUnitLabel } from '@/components/Phrase';
import { AvatarView, Card, Free, PriceView, Reason, ui } from '@/components/Ui';
import type { HelperCard } from '@/lib/types';

/**
 * One person, as a card.
 *
 * Drawn by the results list and by the preview on the search screen, which is
 * the reason it left `Results.tsx`: the preview exists to show what the list
 * will contain, and two copies of this markup would eventually show something
 * else.
 */
export function HelperCardView({
  card,
  locale,
  onClick,
}: {
  card: HelperCard;
  locale: string;
  onClick: () => void;
}) {
  // "Cheaper but unproven" is the one reason that should not wear the same
  // confident green dot as the others.
  const weak = card.reason?.code === 'reason.cheapest_but_unproven';
  // Somebody who published without a line under their name or a price would
  // otherwise be a name alone, which reads as a card that failed to load.
  // In a list of one service the server leaves the service out.
  const subtitle = card.affiliation || card.subject || card.service;

  return (
    <Card onClick={onClick}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
        <AvatarView avatar={card.avatar} size={40} square />
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14.5, fontWeight: 680, letterSpacing: '-0.015em' }}>
            {card.name}
          </div>
          {subtitle ? (
            <div style={{ marginTop: 2, fontSize: 12, color: 'var(--muted)' }}>
              {subtitle}
            </div>
          ) : null}
        </div>
        {card.price?.amount != null ? (
          <PriceView
            price={card.price}
            unitLabel={<PriceUnitLabel unit={card.price.unit} />}
          />
        ) : (
          <span
            className={ui.price}
            style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}
          >
            <Trans>цена договорная</Trans>
          </span>
        )}
      </div>

      {card.reason ? (
        <Reason weak={weak}>
          <PhraseView phrase={card.reason} locale={locale} />
        </Reason>
      ) : null}

      {card.availability ? (
        <Free>
          <PhraseView phrase={card.availability} locale={locale} />
        </Free>
      ) : null}
    </Card>
  );
}
