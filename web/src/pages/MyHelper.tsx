import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { EditIcon, iconForService, PlusIcon } from '@/components/icons';
import { OwnerStatusCard } from '@/components/OwnerStatusCard';
import { PriceUnitLabel } from '@/components/Phrase';
import { ServiceSheet } from '@/components/ServiceSheet';
import { Switch } from '@/components/Switch';
import {
  Action,
  Actions,
  Cards,
  Empty,
  formatMoney,
  Hint,
  Row,
  Rows,
  Screen,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { withPaused } from '@/lib/myServices';
import { ownerStatus, startsListed } from '@/lib/ownerStatus';
import type { MyHelper, MyOffer, ServiceType } from '@/lib/types';

/**
 * «Мои услуги»: what this person offers, each with a switch that takes it out
 * of the catalog and puts it back, and «Изменить» for its price.
 *
 * Everything about the person rather than one service — the text, how and
 * where they work, whether they are listed at all — is one row down, in «О
 * себе и как работаю». A switch here hides one service; hiding everything is
 * «Видимость» there.
 *
 * Adding a service leaves for `/offer`, the same grid used when the person
 * first joined, so somebody who writes theses or fills in residence forms can
 * add what they actually do.
 */
export default function MyHelperPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data, isError } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  // The colour each category wears everywhere else. Cached for an hour and
  // shared with every other screen that needs the reference list.
  const { data: serviceTypes } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  // The profile as the server last said it was, kept across the refetch after
  // «Изменить» saves (afterHelperSaved drops the cached copy), so the list does
  // not turn into a skeleton under the closing sheet.
  const [seen, setSeen] = useState<MyHelper>();
  useEffect(() => {
    if (data) setSeen(data);
  }, [data]);
  const status = seen ? ownerStatus(seen) : null;
  const [editing, setEditing] = useState<number | null>(null);
  const edited = seen?.offers.find((offer) => offer.id === editing);

  // Shown at once and put back if the server says no: a switch that waits for
  // a round trip before it moves reads as one that did not take the tap.
  const pause = useMutation({
    mutationFn: ({ id, paused }: { id: number; paused: boolean }) =>
      api.pauseOffer(id, paused),
    onMutate: async ({ id, paused }) => {
      hapticSelection();
      await queryClient.cancelQueries({ queryKey: ['my-helper'] });
      const before = queryClient.getQueryData<MyHelper>(['my-helper']);
      if (before) queryClient.setQueryData(['my-helper'], withPaused(before, id, paused));
      return { before };
    },
    onError: (_error, _vars, context) => {
      if (context?.before) queryClient.setQueryData(['my-helper'], context.before);
    },
    onSettled: () => {
      // «По твоим услугам», the count on Profile and the catalog's numbers
      // all leave out a switched-off service.
      void queryClient.invalidateQueries({ queryKey: ['my-helper'] });
      void queryClient.invalidateQueries({ queryKey: ['request-feed'] });
      void queryClient.invalidateQueries({ queryKey: ['home'] });
    },
  });

  if (isError && !seen) {
    return (
      <Screen>
        <AppHeader />
        <Empty title={<Trans>Не получилось загрузить анкету</Trans>} />
      </Screen>
    );
  }

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Мои услуги</Trans>
      </Title>
      {seen && status ? (
        <OwnerStatusCard
          status={status}
          helper={seen}
          listed={startsListed(seen)}
          place="services"
        />
      ) : null}

      {!seen ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={4} />
        </div>
      ) : (
        <>
          <div style={{ marginTop: 14 }}>
            {seen.offers.length === 0 ? (
              <Hint>
                <Trans>
                  Пока ни одной. Добавь ниже — без них тебя не найдут по поиску.
                </Trans>
              </Hint>
            ) : (
              <Cards>
                {seen.offers.map((offer) => (
                  <ServiceCard
                    key={offer.id}
                    offer={offer}
                    type={serviceTypes?.find((type) => type.id === offer.service_type_id)}
                    busy={pause.isPending}
                    onSwitch={(on) => pause.mutate({ id: offer.id, paused: !on })}
                    onEdit={() => setEditing(offer.id)}
                  />
                ))}
              </Cards>
            )}
            {pause.isError ? (
              <div style={{ marginTop: 10 }}>
                <Hint>
                  <Trans>Не сохранилось — попробуй ещё раз.</Trans>
                </Hint>
              </div>
            ) : null}
          </div>

          <div style={{ marginTop: 10 }}>
            <Rows>
              <Row
                leading={
                  <Tile tone={1}>
                    <PlusIcon size={19} />
                  </Tile>
                }
                title={<Trans>Добавить услугу</Trans>}
                hint={<Trans>репетиторство, работы, документы</Trans>}
                onClick={() => navigate('/offer')}
              />
              <Row
                leading={
                  <Tile tone={3}>
                    <EditIcon size={19} />
                  </Tile>
                }
                title={<Trans>О себе и как работаю</Trans>}
                hint={<Trans>текст, формат, город, видимость</Trans>}
                onClick={() => navigate('/my-helper/about')}
              />
            </Rows>
          </div>
        </>
      )}

      {seen && edited ? (
        <ServiceSheet offer={edited} helper={seen} onClose={() => setEditing(null)} />
      ) : null}
    </Screen>
  );
}

/**
 * One service as the catalog lists it, with its switch.
 *
 * A switched-off one looks like the rest: only the switch says so. Dimmed, it
 * read as broken, and its «Изменить» as unavailable.
 */
function ServiceCard({
  offer,
  type,
  busy,
  onSwitch,
  onEdit,
}: {
  offer: MyOffer;
  type: ServiceType | undefined;
  busy: boolean;
  onSwitch: (on: boolean) => void;
  onEdit: () => void;
}) {
  const { t } = useLingui();
  const Icon = iconForService(offer.service_type);
  // A service with no subject — writing a thesis, nostrification — is named
  // by what it is, not by the blank where a subject would go.
  const name = offer.subject_name ?? offer.service_type_name;
  return (
    <div className={ui.card}>
      <div className={ui.svcLine}>
        <Tile tone={type?.tone ?? 0}>
          <Icon size={19} />
        </Tile>
        <span className={ui.rowBody}>
          <span className={ui.rowName}>{name}</span>
          <span className={ui.rowHint}>
            {offer.price_amount == null ? (
              <Trans>цена не указана</Trans>
            ) : (
              <>
                {formatMoney(offer.price_amount)} Kč{' '}
                <PriceUnitLabel unit={offer.price_unit} />
              </>
            )}
            {offer.institution_name ? ` · ${offer.institution_name}` : null}
          </span>
        </span>
        <Switch
          checked={!offer.paused}
          busy={busy}
          label={t`${name}: в каталоге`}
          onChange={onSwitch}
        />
      </div>
      <Actions>
        <Action quiet tall onClick={onEdit}>
          <Trans>Изменить</Trans>
        </Action>
      </Actions>
    </div>
  );
}
