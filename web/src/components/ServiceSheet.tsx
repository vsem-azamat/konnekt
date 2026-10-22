import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';

import { Sheet } from '@/components/Sheet';
import { Action, Actions, Label, Reason, ui } from '@/components/Ui';
import { hapticSuccess } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { afterHelperSaved } from '@/lib/helperSaved';
import { keepsListed, offersWith } from '@/lib/myServices';
import type { MyHelper, MyOffer, PriceUnit } from '@/lib/types';

/**
 * «Изменить» on one service: its price, what the price is per, and the way to
 * drop it. Saved from here, so the list behind needs no «Сохранить» of its own.
 */
export function ServiceSheet({
  offer,
  helper,
  onClose,
}: {
  offer: MyOffer;
  helper: MyHelper;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { t } = useLingui();
  // Rounded, because the field holds digits: an older row saved as 550.5
  // would otherwise render a decimal point the input then refuses to accept.
  const [price, setPrice] = useState(
    offer.price_amount == null ? '' : String(Math.round(offer.price_amount)),
  );
  const [unit, setUnit] = useState<PriceUnit>(offer.price_unit);
  // Removal takes a second tap: the first one is easy to make by mistake at
  // the bottom of a sheet, and nothing brings a removed service back.
  const [removing, setRemoving] = useState(false);
  // «Да, убрать» takes the place of the first button, so a double tap would
  // press both. Taps on it in the first moment after it appears are ignored.
  const armedAt = useRef(0);

  const save = useMutation({
    mutationFn: (change: { price_amount: number | null; price_unit: PriceUnit } | null) =>
      api.saveHelper({
        offers: offersWith(helper.offers, offer.id, change),
        publish: keepsListed(helper),
      }),
    onSuccess: (me) => {
      hapticSuccess();
      afterHelperSaved(queryClient, me);
      onClose();
    },
  });

  /*
   * A native select: it shows what the alternatives are, opens the platform's
   * own picker on a phone, and follows `color-scheme` in both themes.
   *
   * Every unit, not the popular four. A select whose value is missing from its
   * options renders the first one instead, so a service priced per semester
   * would show "за час" and be saved that way.
   */
  const units: { value: PriceUnit; label: string }[] = [
    { value: 'hour', label: t`за час` },
    { value: 'lesson', label: t`за занятие` },
    { value: 'work', label: t`за работу` },
    { value: 'day', label: t`в день` },
    { value: 'week', label: t`за неделю` },
    { value: 'month', label: t`в месяц` },
    { value: 'semester', label: t`за семестр` },
    { value: 'item', label: t`за штуку` },
    { value: 'negotiable', label: t`договорная` },
  ];

  return (
    <Sheet
      title={offer.subject_name ?? offer.service_type_name}
      closeLabel={t`Закрыть`}
      // Not while the save is on its way: closing then would look like a
      // cancel, and the change would land anyway.
      onClose={() => {
        if (!save.isPending) onClose();
      }}
    >
      {offer.institution_name ? (
        <p className={ui.sheetNote}>{offer.institution_name}</p>
      ) : null}
      <Label>
        <Trans>Цена</Trans>
      </Label>
      <div className={ui.field}>
        <input
          value={price}
          /*
           * Digits only, filtered as they are typed. Prices here are whole
           * crowns, and parsing free text was a way to be quietly wrong: "1,500"
           * became 1.5 Kč on a keyboard where a comma is a decimal point, and
           * "1 500" became nothing at all.
           */
          onChange={(event) =>
            setPrice(event.target.value.replace(/\D/g, '').slice(0, 7))
          }
          placeholder={t`Kč`}
          inputMode="numeric"
          aria-label={t`Цена`}
          style={{
            all: 'unset',
            flex: 1,
            minWidth: 0,
            fontVariantNumeric: 'tabular-nums',
          }}
        />
        {/* The currency stays once a price is typed: the placeholder alone
            left a bare «600 за час». */}
        {price !== '' ? <span>{t`Kč`}</span> : null}
        <select
          value={unit}
          onChange={(event) => setUnit(event.target.value as PriceUnit)}
          aria-label={t`За что цена`}
          style={{ all: 'unset', fontSize: 13, color: 'var(--muted)', cursor: 'pointer' }}
        >
          {units.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      {save.isError ? (
        <Reason weak>
          <Trans>Не сохранилось — попробуй ещё раз.</Trans>
        </Reason>
      ) : null}
      <Actions>
        <Action
          tall
          disabled={save.isPending}
          onClick={() =>
            // Empty means "did not say", not free.
            save.mutate({ price_amount: price ? Number(price) : null, price_unit: unit })
          }
        >
          <Trans>Сохранить</Trans>
        </Action>
      </Actions>
      <Actions>
        {removing ? (
          <Action
            quiet
            danger
            disabled={save.isPending}
            onClick={() => {
              if (Date.now() - armedAt.current > 400) save.mutate(null);
            }}
          >
            <Trans>Да, убрать</Trans>
          </Action>
        ) : (
          <Action
            quiet
            onClick={() => {
              armedAt.current = Date.now();
              setRemoving(true);
            }}
          >
            <Trans>Убрать услугу</Trans>
          </Action>
        )}
      </Actions>
    </Sheet>
  );
}
