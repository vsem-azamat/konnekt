import { Trans, useLingui } from '@lingui/react/macro';
import { useQuery } from '@tanstack/react-query';
import { useEffect, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { ServiceGrid } from '@/components/ServiceGrid';
import { Empty, Hint, Screen, SkeletonRows, Sub, Title, ui } from '@/components/Ui';
import { hapticSelection, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import type { OfferOpened } from '@/lib/generated/types.gen';

/**
 * What can you help with?
 *
 * This replaced a textarea. Someone used to write a paragraph and a parser
 * guessed subjects and a price out of it, which made the parser the gatekeeper:
 * a person offering something the taxonomy had never heard of wrote three
 * sentences and got nothing back. Tiles cannot fail to be understood.
 *
 * Multiple choice, not one at a time. The people worth having in the catalog
 * are the ones who can do four things, and asking them to walk the same form
 * four times is how you end up with a catalog of people who can do one.
 *
 * Tiles the person already offers start ticked. That is not a convenience: the
 * save replaces the whole offer list, so a screen that started empty would
 * quietly delete everything they had the moment they added something new.
 *
 * A way in may name a service as well (`state.picked`), for the empty shelf on
 * the home screen and the results list to open this with the service the
 * person was looking at (konnekt-ratings' change to those screens). It is
 * ticked on top of what they already offer, never instead.
 */
export default function OfferPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useLingui();
  const entry = location.state as {
    picked?: string[];
    from?: OfferOpened['source'];
  } | null;
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [loaded, setLoaded] = useState(false);

  const {
    data: serviceTypes,
    isPending,
    isError: typesFailed,
  } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const { data: mine, isError: profileFailed } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  // Either failure leaves this screen with nothing true to draw, and `loaded`
  // needs both — so without this the skeleton would spin for ever.
  const isError = typesFailed || profileFailed;

  // Once, from the server. Re-running this on every render would undo each tap
  // the moment the query refetched.
  useEffect(() => {
    if (!mine || !serviceTypes || loaded) return;
    const byId = new Map(serviceTypes.map((type) => [type.id, type.code]));
    const already = new Set<string>();
    for (const offer of mine.offers) {
      const code = byId.get(offer.service_type_id);
      if (code) already.add(code);
    }
    // Only codes the grid has: a stale or hand-written link must not tick a
    // tile nobody can see and then send it as an offer.
    const known = new Set(serviceTypes.map((type) => type.code));
    for (const code of entry?.picked ?? []) if (known.has(code)) already.add(code);
    setPicked(already);
    setLoaded(true);
  }, [mine, serviceTypes, loaded, entry]);

  // Once per visit, for the catalog's count of who looked at offering. The ref
  // and not the effect's own deps: React runs a mount effect twice in
  // development, and twice would be counted twice.
  const reported = useRef(false);
  useEffect(() => {
    if (reported.current) return;
    reported.current = true;
    api.reportOfferOpen(entry?.from ?? 'other').catch(() => {});
  }, [entry]);

  const toggle = (code: string) => {
    hapticSelection();
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  /*
   * Nothing may leave this screen before the person's current services have
   * arrived. The next screen sends an authoritative offer list and the server
   * deletes whatever is missing from it, so walking on with a half-loaded set
   * of ticks publishes a list that silently drops everything they already had.
   * `/helper` does more work than `/taxonomy/service-types`, so it really is
   * the slower of the two.
   */
  useMainButton(
    loaded && picked.size > 0
      ? {
          text: t`Дальше · ${picked.size}`,
          isVisible: true,
          isEnabled: true,
          onClick: () => navigate('/offer/prices', { state: { picked: [...picked] } }),
        }
      : { text: t`Выбери, чем можешь помочь`, isVisible: true, isEnabled: false },
  );

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Чем ты можешь помочь?</Trans>
      </Title>
      <Sub>
        <Trans>Отметь всё, что умеешь. Цены спросим на следующем экране.</Trans>
      </Sub>

      {/* Refusing to draw the grid rather than drawing it empty. Without the
          profile we do not know what is already offered, and every tick made
          before it arrives is one the effect above overwrites — or worse, one
          that publishes a list missing everything the person had. */}
      {isError ? (
        <Empty
          title={<Trans>Не получилось загрузить анкету</Trans>}
          body={<Trans>Проверь связь и попробуй ещё раз.</Trans>}
        />
      ) : !loaded || isPending || !serviceTypes ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={6} />
        </div>
      ) : (
        <ServiceGrid
          items={serviceTypes}
          selected={picked}
          onToggle={toggle}
          renderNote={(group) =>
            group === 'life' ? (
              <div style={{ marginTop: -4, marginBottom: 10 }}>
                <Hint>
                  {/* Private people offer these for free. A company is sent
                      to the ads page instead: catalog/docs/architecture.md. */}
                  <Trans>
                    Людям бесплатно. Компаниям —{' '}
                    <a
                      href="/ads"
                      className={ui.inlineLink}
                      onClick={(event) => {
                        event.preventDefault();
                        navigate('/ads');
                      }}
                    >
                      реклама для студентов
                    </a>
                    .
                  </Trans>
                </Hint>
              </div>
            ) : null
          }
        />
      )}
    </Screen>
  );
}
