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

  const { data, isError, refetch } = useQuery({
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
  //
  // For showing only. A save sends the whole list, and until the refetch lands
  // this copy still has the service just removed or the price just changed: a
  // second save built from it would put them back. So the switches and
  // «Изменить» wait for `data`.
  const [seen, setSeen] = useState<MyHelper>();
  useEffect(() => {
    if (data) setSeen(data);
  }, [data]);
  const status = seen ? ownerStatus(seen) : null;
  const [editing, setEditing] = useState<number | null>(null);
  const edited = data?.offers.find((offer) => offer.id === editing);

  // Shown at once and put back if the server says no: a switch that waits for
  // a round trip before it moves reads as one that did not take the tap.
  const pause = useMutation({
    mutationFn: ({ id, paused }: { id: number; paused: boolean }) =>
      api.pauseOffer(id, paused),
    onMutate: async ({ id, paused }) => {
      hapticSelection();
      await queryClient.cancelQueries({ queryKey: ['my-helper'] });
      queryClient.setQueryData<MyHelper>(
        ['my-helper'],
        (current) => current && withPaused(current, id, paused),
      );
    },
    // That one switch back, not a snapshot of the whole profile: a price saved
    // while the request was out would be undone with it.
    onError: (_error, { id, paused }) => {
      queryClient.setQueryData<MyHelper>(
        ['my-helper'],
        (current) => current && withPaused(current, id, !paused),
      );
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
                    busy={!data || (pause.isPending && pause.variables?.id === offer.id)}
                    onSwitch={(on) => pause.mutate({ id: offer.id, paused: !on })}
                    ready={Boolean(data)}
                    onEdit={() => setEditing(offer.id)}
                  />
                ))}
              </Cards>
            )}
            {pause.isError ? (
              <div style={{ marginTop: 10 }} role="status">
                <Hint>
                  <Trans>Не сохранилось — попробуй ещё раз.</Trans>
                </Hint>
              </div>
            ) : null}
            {isError && !data ? (
              <div style={{ marginTop: 10 }} role="status">
                <Hint>
                  <Trans>Не получилось обновить список.</Trans>
                </Hint>
                <Actions>
                  <Action quiet onClick={() => void refetch()}>
                    <Trans>Попробовать ещё раз</Trans>
                  </Action>
                </Actions>
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

      {data && edited ? (
        <ServiceSheet offer={edited} helper={data} onClose={() => setEditing(null)} />
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
  ready,
  onSwitch,
  onEdit,
}: {
  offer: MyOffer;
  type: ServiceType | undefined;
  busy: boolean;
  /** The list is the server's own, not the copy kept across a refetch. */
  ready: boolean;
  onSwitch: (on: boolean) => void;
  onEdit: () => void;
}) {
  const { t } = useLingui();
  const Icon = iconForService(offer.service_type);
  // A service with no subject — writing a thesis, nostrification — is named
  // by what it is, not by the blank where a subject would go.
  const name = offer.subject_name ?? offer.service_type_name;
  // The same subject can be offered at two schools.
  const fullName = offer.institution_name ? `${name}, ${offer.institution_name}` : name;
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
          label={t`${fullName}: в каталоге`}
          onChange={onSwitch}
        />
      </div>
      <Actions>
        <Action
          quiet
          tall
          disabled={!ready}
          label={t`Изменить: ${fullName}`}
          onClick={onEdit}
        >
          <Trans>Изменить</Trans>
        </Action>
      </Actions>
    </div>
  );
}
