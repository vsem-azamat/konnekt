import { Trans, useLingui } from '@lingui/react/macro';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { iconForService } from '@/components/icons';
import { ServiceGroupLabel } from '@/components/Phrase';
import { Sheet } from '@/components/Sheet';
import { Action, Actions, Label, Row, Rows, Tile } from '@/components/Ui';
import { showcasePhoto } from '@/lib/api';
import { handleOf, type Place, priceFrom, type Shelf } from '@/lib/showcase';
import type { HomeSection, ShowcaseCard } from '@/lib/types';

import css from './Showcase.module.css';

/**
 * «Документы и жизнь» with its paid places: the first big, the next two as a
 * pair under it (three equal tiles from 720px), then the shelf's other services
 * as rows. Drawn only when `shelf()` says there is something to draw.
 */
export function Showcase({
  shelf,
  contact,
  onPick,
}: {
  shelf: Shelf;
  contact: string | null | undefined;
  /** What a plain row does, the same as its tile on the grid. */
  onPick: (section: HomeSection) => void;
}) {
  const [first, ...rest] = shelf.places;
  const place = (one: Place, main = false) =>
    one.kind === 'card' ? (
      <PartnerCard key={`card-${one.card.id}`} card={one.card} main={main} />
    ) : (
      <OpenPlace
        key={`open-${one.section.code}`}
        section={one.section}
        contact={contact}
        main={main}
      />
    );
  return (
    <>
      <Label>
        <ServiceGroupLabel group="life" />
      </Label>
      {first ? (
        <div className={css.hero}>
          {place(first, rest.length > 0)}
          {rest.length > 0 ? (
            <div className={css.pair}>{rest.map((one) => place(one))}</div>
          ) : null}
        </div>
      ) : null}
      {shelf.rows.length > 0 ? (
        <div className={first ? css.rows : undefined}>
          <Rows>
            {shelf.rows.map((section) => {
              const Icon = iconForService(section.code);
              return (
                <Row
                  key={section.code}
                  leading={
                    <Tile tone={section.tone}>
                      <Icon size={19} />
                    </Tile>
                  }
                  title={section.name}
                  hint={section.hint}
                  onClick={() => onPick(section)}
                />
              );
            })}
          </Rows>
        </div>
      ) : null}
    </>
  );
}

function PartnerCard({ card, main }: { card: ShowcaseCard; main: boolean }) {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  const amount = priceFrom(card.price_from, i18n.locale);
  return (
    <button
      type="button"
      className={`${css.card}${main ? ` ${css.main}` : ''}`}
      onClick={() => navigate(`/partner/${card.id}`)}
    >
      <span className={css.coverWrap}>
        {card.photo ? (
          <img className={css.cover} src={showcasePhoto(card.photo)} alt="" />
        ) : (
          <span className={css.cover} />
        )}
        <span className={css.badge}>
          <Trans>Партнёр</Trans>
        </span>
      </span>
      <span className={css.body}>
        <span className={css.title}>{card.title}</span>
        {card.line ? <span className={css.line}>{card.line}</span> : null}
        <span className={css.meta}>
          <span className={css.provider}>{card.partner}</span>
          {amount ? (
            <span className={css.price}>
              <Trans>от {amount} Kč</Trans>
            </span>
          ) : null}
        </span>
      </span>
    </button>
  );
}

/** A place nobody has taken (E1): an invitation, lower than a card. */
function OpenPlace({
  section,
  contact,
  main,
}: {
  section: HomeSection;
  contact: string | null | undefined;
  main: boolean;
}) {
  const [open, setOpen] = useState(false);
  const Icon = iconForService(section.code);
  return (
    <>
      <button
        type="button"
        className={`${css.card} ${css.open}${main ? ` ${css.main}` : ''}`}
        onClick={() => setOpen(true)}
      >
        <span className={css.openCover}>
          <Tile tone={section.tone}>
            <Icon size={22} />
          </Tile>
        </span>
        <span className={css.body}>
          <span className={css.title}>{section.name}</span>
          <span className={css.line}>
            <Trans>Твоя услуга здесь</Trans>
          </span>
          <span className={css.meta}>
            <span className={`${css.price} ${css.invite}`}>
              <Trans>Разместить ›</Trans>
            </span>
          </span>
        </span>
      </button>
      {open && contact ? (
        <OpenPlaceSheet
          service={section.name}
          contact={contact}
          onClose={() => setOpen(false)}
        />
      ) : null}
    </>
  );
}

function OpenPlaceSheet({
  service,
  contact,
  onClose,
}: {
  service: string;
  contact: string;
  onClose: () => void;
}) {
  const { t } = useLingui();
  const handle = handleOf(contact);
  return (
    <Sheet
      title={<Trans>{service} — место для партнёра</Trans>}
      onClose={onClose}
      closeLabel={t`Закрыть`}
    >
      <p className={css.sheetText}>
        <Trans>
          Хочешь, чтобы здесь была твоя услуга? Напиши нам — обсудим условия. Карточку с
          фото и текстом сделаем сами.
        </Trans>
      </p>
      <Actions>
        <Action tall onClick={() => openTelegramLink(contact)}>
          <Trans>Написать в Telegram</Trans>
        </Action>
      </Actions>
      {handle ? (
        <div className={css.sheetFine}>
          <Trans>Откроется чат с {handle}</Trans>
        </div>
      ) : null}
    </Sheet>
  );
}
