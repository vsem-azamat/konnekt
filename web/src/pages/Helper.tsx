import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery } from '@tanstack/react-query';
import { openTelegramLink } from '@tma.js/sdk-react';
import { useParams } from 'react-router';
import { AppHeader } from '@/components/AppHeader';
import { PriceUnitLabel, StatLabel } from '@/components/Phrase';
import {
  AvatarView,
  Card,
  Cards,
  Chips,
  ChipView,
  Empty,
  formatMoney,
  Heading,
  Hint,
  Label,
  Screen,
  SkeletonRows,
  Sub,
  ui,
} from '@/components/Ui';
import { hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { offerChipText } from '@/lib/offerChip';
import { TurnaroundLabel } from '@/lib/turnaround';
import type { HelperDetail } from '@/lib/types';

/**
 * One person's page.
 *
 * Three numbers instead of a paragraph about themselves, and the price sits in
 * the button — nobody should have to open a chat to find out what an hour
 * costs.
 */
export default function HelperPage() {
  const { id } = useParams<{ id: string }>();
  const { t, i18n } = useLingui();

  const { data, isPending, isError } = useQuery({
    queryKey: ['helper', id],
    queryFn: ({ signal }) => api.getHelper(Number(id), signal),
    enabled: Boolean(id),
  });

  const price = data?.offers.find((offer) => offer.price.amount != null)?.price;

  // In the student's own language: it is the student who sends it.
  const subjects = String(data?.intro_context.subjects ?? '');
  const intro = [
    t`Привет! Пишу тебе из Konnekt.`,
    subjects ? t`Нужна помощь: ${subjects}.` : t`Нужна помощь с учёбой.`,
  ].join('\n');

  const contact = useMutation({
    mutationFn: () => api.startContact(Number(id)),
    onSuccess: (result) => {
      hapticSuccess();
      openTelegramLink(withIntro(result.telegram_url, intro));
    },
    onError: () => {
      // The link is worth opening even if we failed to record the attempt —
      // losing a statistic is better than losing the introduction.
      if (data?.telegram_url) openTelegramLink(withIntro(data.telegram_url, intro));
    },
  });

  useMainButton(
    data?.telegram_url
      ? {
          text: price?.amount
            ? t`Написать · ${formatMoney(price.amount)} Kč`
            : t`Написать`,
          isVisible: true,
          isEnabled: !contact.isPending,
          isLoaderVisible: contact.isPending,
          onClick: () => contact.mutate(),
        }
      : null,
  );

  if (isPending) {
    return (
      <Screen>
        <AppHeader />
        <div style={{ height: 16 }} />
        <SkeletonRows count={5} />
      </Screen>
    );
  }

  if (isError || !data) {
    return (
      <Screen>
        <AppHeader />
        <Empty
          title={<Trans>Профиль недоступен</Trans>}
          body={<Trans>Возможно, человек скрыл его.</Trans>}
        />
      </Screen>
    );
  }

  return (
    <Screen>
      <AppHeader />
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', paddingTop: 8 }}>
        <AvatarView avatar={data.avatar} size={58} square />
        <div style={{ minWidth: 0 }}>
          <Heading>{data.name}</Heading>
          {data.affiliation ? (
            <div style={{ marginTop: 4 }}>
              <Sub>{data.affiliation}</Sub>
            </div>
          ) : null}
        </div>
      </div>

      {data.stats.length > 0 ? (
        <div
          style={{
            display: 'flex',
            marginTop: 16,
            borderRadius: 14,
            background: 'var(--surface)',
            overflow: 'hidden',
          }}
        >
          {data.stats.map((stat) => (
            <div
              key={stat.code}
              style={{ flex: 1, padding: '11px 4px', textAlign: 'center' }}
            >
              <b
                style={{
                  display: 'block',
                  fontSize: 16,
                  fontWeight: 750,
                  letterSpacing: '-0.02em',
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {stat.value}
              </b>
              <span style={{ fontSize: 10.5, color: 'var(--muted)' }}>
                <StatLabel code={stat.code} value={stat.value} />
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {data.offers.length > 0 ? (
        <>
          <Label>
            <Trans>Чем помогает</Trans>
          </Label>
          <Chips>
            {data.offers.map((offer) => (
              <ChipView key={offer.id}>{offerChipText(offer)}</ChipView>
            ))}
          </Chips>
        </>
      ) : null}

      {/* What an errand actually covers, in our words, and then in theirs. A
          chip saying "Insurance" is the same chip for everybody offering it;
          these lines are the difference between two people. */}
      {coveredBy(data.offers).map(({ code, name, options, note, turnaround }) => (
        <div key={`covers-${code}`}>
          <Label>{name}</Label>
          {options.length > 0 ? (
            <ul className={ui.covers}>
              {options.map((label) => (
                <li key={label}>{label}</li>
              ))}
            </ul>
          ) : null}
          {/* Only a written work carries one, and it is the question asked
              straight after the price, so it sits above their own words. */}
          {turnaround != null ? (
            <div style={{ marginTop: options.length > 0 ? 8 : 0 }}>
              <Sub>
                <Trans>
                  Срок: <TurnaroundLabel days={turnaround} />
                </Trans>
              </Sub>
            </div>
          ) : null}
          {note ? (
            <div style={{ marginTop: options.length > 0 || turnaround != null ? 8 : 0 }}>
              <Sub>{note}</Sub>
            </div>
          ) : null}
        </div>
      ))}

      {data.about ? (
        <>
          <Label>
            <Trans>Как проходит</Trans>
          </Label>
          <Sub>{data.about}</Sub>
        </>
      ) : null}

      {data.free_slots.length > 0 ? (
        <>
          <Label>
            <Trans>Свободные окна</Trans>
          </Label>
          <Chips>
            {data.free_slots.map((slot) => (
              <ChipView key={slot} active>
                {new Intl.DateTimeFormat(i18n.locale, {
                  day: 'numeric',
                  month: 'short',
                  hour: '2-digit',
                  minute: '2-digit',
                }).format(new Date(slot))}
              </ChipView>
            ))}
          </Chips>
        </>
      ) : null}

      {data.offers.length > 0 ? (
        <>
          <Label>
            <Trans>Сколько стоит</Trans>
          </Label>
          <Cards>
            {data.offers
              .filter((offer) => offer.price.amount != null)
              .map((offer) => (
                <Card key={`price-${offer.id}`}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                    <span style={{ fontSize: 14, fontWeight: 600, minWidth: 0 }}>
                      {offer.subject ?? offer.service_type_name}
                    </span>
                    <span
                      style={{
                        marginLeft: 'auto',
                        flex: 'none',
                        whiteSpace: 'nowrap',
                        fontSize: 14,
                        fontWeight: 700,
                        fontVariantNumeric: 'tabular-nums',
                      }}
                    >
                      {formatMoney(offer.price.amount ?? 0)} Kč
                    </span>
                    <span
                      style={{
                        flex: 'none',
                        whiteSpace: 'nowrap',
                        fontSize: 11.5,
                        color: 'var(--muted)',
                      }}
                    >
                      <PriceUnitLabel unit={offer.price.unit} />
                    </span>
                  </div>
                </Card>
              ))}
          </Cards>
        </>
      ) : null}

      {data.place_note ? (
        <div style={{ marginTop: 14 }}>
          <Hint>{data.place_note}</Hint>
        </div>
      ) : null}

      {!data.telegram_url ? (
        <div style={{ marginTop: 14 }}>
          <Hint>
            <Trans>
              У этого человека нет открытого username в Telegram, написать не получится.
            </Trans>
          </Hint>
        </div>
      ) : null}
    </Screen>
  );
}

/**
 * The first message, written for them.
 *
 * The hardest part of any directory is not finding someone, it is working out
 * what to say. Telegram's deep link carries prefilled text, so the chat opens
 * with the message already in it.
 */
function withIntro(url: string, text: string): string {
  return `${url}?text=${encodeURIComponent(text)}`;
}

/**
 * What each kind of help covers, one entry per kind.
 *
 * By service type and not by offer row: the screen that writes these puts the
 * same checklist on every row of a service, so two subjects would otherwise
 * print the same paragraph twice. Not a run-length grouping either — the API
 * does not order a helper's offers, so two rows of one service need not be
 * adjacent — and the first row carrying anything wins, because a service whose
 * first row happens to be blank still has something to say.
 */
function coveredBy(offers: HelperDetail['offers']) {
  const out = new Map<
    string,
    {
      code: string;
      name: string;
      options: string[];
      note: string | null;
      turnaround: number | null;
    }
  >();
  for (const offer of offers) {
    if (!offer.options.length && !offer.note && offer.turnaround_days == null) continue;
    if (out.has(offer.service_type)) continue;
    out.set(offer.service_type, {
      code: offer.service_type,
      name: offer.service_type_name,
      options: offer.options,
      note: offer.note,
      turnaround: offer.turnaround_days,
    });
  }
  return [...out.values()];
}
