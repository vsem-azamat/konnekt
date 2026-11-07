import { Trans } from '@lingui/react/macro';
import { openLink } from '@tma.js/sdk-react';
import type { ReactNode } from 'react';

import { api } from '@/lib/api';
import { track } from '@/lib/track';
import type { Placement } from '@/lib/types';

import { Hint, ui } from './Ui';

/**
 * One partner placement, outlined and labelled «Партнёр».
 *
 * Shared by «Не про учёбу», where partners are shown, and the ads page, where
 * a business sees what it would buy. Two copies would drift, and the second
 * one would be a promise about the first.
 */
export function PartnerBlock({
  placement,
  preview = false,
}: {
  placement: Placement;
  /** Shown as an example — on the ads page, or in the console while a card is
   *  written: not a button, and never counted as a click, which would bill the
   *  partner for somebody looking at it. */
  preview?: boolean;
}) {
  const open = () => {
    // Counted before the browser leaves, and deliberately not awaited: the tap
    // should open the link now, not after a round trip.
    void api.registerPlacementClick(placement.id).catch(() => undefined);
    track('partner_tap', { from: 'block' });
    openLink(placement.url);
  };

  return (
    <div>
      {placement.context_note ? (
        <div style={{ marginBottom: 9 }}>
          <Hint>{placement.context_note}</Hint>
        </div>
      ) : null}

      <Card preview={preview} onOpen={open}>
        <span className={ui.partnerLabel}>
          <Trans>Партнёр</Trans>
        </span>
        <span className={ui.partnerTop}>
          {placement.logo_text ? (
            <span
              className={ui.partnerLogo}
              style={{ background: placement.logo_bg ?? 'var(--surface)' }}
            >
              {placement.logo_text}
            </span>
          ) : null}
          <span style={{ minWidth: 0 }}>
            <span className={ui.partnerName}>{placement.title}</span>
            {placement.subtitle ? (
              <span
                style={{
                  display: 'block',
                  marginTop: 2,
                  fontSize: 11.5,
                  color: 'var(--muted)',
                }}
              >
                {placement.subtitle}
              </span>
            ) : null}
          </span>
          {placement.price_text ? (
            <span className={ui.partnerPrice}>{placement.price_text}</span>
          ) : null}
        </span>
      </Card>
    </div>
  );
}

/** The card's frame: a button that opens the partner, or a still picture of one. */
function Card({
  preview,
  onOpen,
  children,
}: {
  preview: boolean;
  onOpen: () => void;
  children: ReactNode;
}) {
  if (preview) {
    return <div className={ui.partner}>{children}</div>;
  }
  return (
    <button type="button" className={`${ui.partner} ${ui.pressable}`} onClick={onOpen}>
      {children}
    </button>
  );
}
