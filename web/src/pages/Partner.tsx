import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { openLink, openTelegramLink } from '@tma.js/sdk-react';
import { useParams } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import css from '@/components/Showcase.module.css';
import { Empty, Screen, SkeletonRows, Title } from '@/components/Ui';
import { useMainButton } from '@/hooks/useTelegram';
import { api, showcasePhoto } from '@/lib/api';
import { priceFrom } from '@/lib/showcase';

const TELEGRAM = /^https:\/\/(t\.me|telegram\.me)\//;

/**
 * A paid card from the home showcase, opened: its photo, its text, and
 * «Написать», which goes to the partner. Labelled as a partner's, as every
 * card that is not ours is. A card taken down is not found, the same as one
 * that never was.
 */
export default function PartnerPage() {
  const { id } = useParams();
  const cardId = Number(id);
  const { t, i18n } = useLingui();
  const { data, isPending, isError } = useQuery({
    queryKey: ['showcase-card', cardId],
    queryFn: ({ signal }) => api.getShowcaseCard(cardId, signal),
    enabled: Number.isInteger(cardId) && cardId > 0,
  });

  useMainButton(
    data
      ? {
          text: t`Написать`,
          isVisible: true,
          isEnabled: true,
          onClick: () => {
            // Billed per click, so recorded before the link leaves the app;
            // a failure to record must not keep the student from writing.
            void api.registerPlacementClick(data.id).catch(() => undefined);
            if (TELEGRAM.test(data.write_to)) openTelegramLink(data.write_to);
            else openLink(data.write_to);
          },
        }
      : null,
  );

  if (isPending && !isError) {
    return (
      <Screen>
        <AppHeader />
        <SkeletonRows count={3} />
      </Screen>
    );
  }
  if (!data) {
    return (
      <Screen>
        <AppHeader />
        <Empty
          title={<Trans>Предложение закончилось</Trans>}
          body={<Trans>Партнёр больше не показывает эту карточку.</Trans>}
        />
      </Screen>
    );
  }

  const amount = priceFrom(data.price_from, i18n.locale);
  const until = data.until
    ? new Intl.DateTimeFormat(i18n.locale, { day: 'numeric', month: 'long' }).format(
        new Date(data.until),
      )
    : null;
  return (
    <Screen>
      <AppHeader />
      {data.photo ? (
        <img className={css.pageCover} src={showcasePhoto(data.photo)} alt="" />
      ) : null}
      <div className={css.who}>
        <b>{data.partner}</b>
        <span className={css.service}>
          <Trans>Партнёр Konnekt</Trans>
        </span>
      </div>
      <div style={{ marginTop: 6 }}>
        <Title>{data.title}</Title>
      </div>
      {amount ? (
        <div className={css.from}>
          <Trans>от {amount} Kč</Trans>
        </div>
      ) : null}
      {data.text ? <p className={css.text}>{data.text}</p> : null}
      {until ? (
        <p className={css.fine}>
          <Trans>Размещено до {until}</Trans>
        </p>
      ) : null}
    </Screen>
  );
}
