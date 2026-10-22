import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';

import { AppHeader } from '@/components/AppHeader';
import { LockIcon } from '@/components/icons';
import { OwnerStatusCard } from '@/components/OwnerStatusCard';
import {
  Empty,
  Hint,
  Label,
  Screen,
  Segmented,
  SkeletonRows,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { afterHelperSaved } from '@/lib/helperSaved';
import { ownerStatus, startsListed } from '@/lib/ownerStatus';
import type { MyHelper, WorkFormat } from '@/lib/types';
import { askedFormat, formatOptions, formatQuestion } from '@/lib/workFormat';

/**
 * «О себе и как работаю»: everything about the person rather than about one
 * service — the text, how and where they work, whether they are listed, and
 * whether the bot writes about new requests.
 *
 * Saves without `offers`, which the server then leaves as they are: the
 * services and their switches belong to «Мои услуги», one screen back.
 */
export default function MyHelperAboutPage() {
  const queryClient = useQueryClient();
  const { t } = useLingui();

  const { data, isError } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  // Which questions this person's services actually have. Cached for an hour
  // and shared with every other screen that needs the reference list.
  const { data: serviceTypes } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const [headline, setHeadline] = useState('');
  const [about, setAbout] = useState('');
  const [city, setCity] = useState('');
  const [placeNote, setPlaceNote] = useState('');
  const [workFormat, setWorkFormat] = useState<WorkFormat>('both');
  const [listed, setListed] = useState(true);
  const [alerts, setAlerts] = useState(true);
  // The profile as the server last said it was, kept across the refetch after
  // a save (afterHelperSaved drops the cached copy), so the status above the
  // form does not blink out while the new one loads.
  const [seen, setSeen] = useState<MyHelper>();
  useEffect(() => {
    if (data) setSeen(data);
  }, [data]);
  const status = seen ? ownerStatus(seen) : null;
  // Only an operator lifts their hide; a save there keeps it hidden, and says so.
  const banned = status === 'banned';
  const [savedHidden, setSavedHidden] = useState(false);

  // Until the reference list is here — still loading, or failed — the neutral
  // wording rather than nothing. Otherwise the question and the whole city
  // block are missing from a screen that already renders a live Save button,
  // and then appear: on a cold cache as a flicker, on a failure for ever, with
  // the person never learning a question existed.
  const asked = useMemo(
    () =>
      askedFormat(
        (seen?.offers ?? []).map((offer) => offer.service_type),
        serviceTypes,
      ),
    [serviceTypes, seen],
  );

  // Filled once, from the server. Later renders must not clobber what the
  // person is typing, which is what a plain `value={data.about}` would do.
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    if (!data || loaded) return;
    setHeadline(data.headline ?? '');
    setAbout(data.about ?? '');
    setCity(data.city ?? '');
    setPlaceNote(data.place_note ?? '');
    setWorkFormat(data.work_format);
    setListed(startsListed(data));
    setAlerts(data.new_request_alerts ?? true);
    setLoaded(true);
  }, [data, loaded]);

  const save = useMutation({
    mutationFn: () =>
      api.saveHelper({
        headline: headline.trim() || null,
        about: about.trim() || null,
        // Omitted, not defaulted, when the form did not ask: `HelperUpsert`
        // reads `model_fields_set`, so a field absent from the payload leaves
        // the stored value alone. Sending `both` for somebody who only writes
        // theses would be the screen answering a question on their behalf.
        ...(asked === null ? {} : { work_format: workFormat }),
        city: city.trim() || null,
        place_note: placeNote.trim() || null,
        publish: listed,
        new_request_alerts: alerts,
      }),
    onMutate: () => setSavedHidden(false),
    onSuccess: (me) => {
      hapticSuccess();
      setSavedHidden(me.helper_status === 'banned');
      afterHelperSaved(queryClient, me);
    },
  });

  // Null while the profile has not arrived, so the error screen below does not
  // get a disabled Save button floating over it with nothing to save.
  useMainButton(
    loaded
      ? {
          text: t`Сохранить`,
          isVisible: true,
          isEnabled: !save.isPending,
          isLoaderVisible: save.isPending,
          onClick: () => save.mutate(),
        }
      : null,
  );

  // Keyed on the form, not on the query: a save drops the cached profile
  // (afterHelperSaved), and the refetch after it must neither swap the form
  // for a skeleton mid-edit nor replace a loaded form with an error.
  if (isError && !loaded) {
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
        <Trans>О себе и как работаю</Trans>
      </Title>
      {seen && status ? (
        <OwnerStatusCard status={status} helper={seen} listed={listed} place="about" />
      ) : null}

      {!loaded ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={5} />
        </div>
      ) : (
        <>
          {/* The line under the name on every card in the catalog. It was
              being written by nothing and read by three screens, which is how
              it got silently erased; giving it an owner fixes that end too. */}
          <Label>
            <Trans>Строчка под именем</Trans>
          </Label>
          <div className={ui.field}>
            <input
              value={headline}
              onChange={(event) => setHeadline(event.target.value)}
              placeholder={t`ČVUT FEL, 3 курс`}
              maxLength={160}
              style={{ all: 'unset', width: '100%' }}
            />
          </div>

          <Label>
            <Trans>О себе</Trans>
          </Label>
          <div className={ui.field} style={{ alignItems: 'flex-start' }}>
            <textarea
              value={about}
              onChange={(event) => setAbout(event.target.value)}
              placeholder={t`Что преподаёшь, где учишься, как проходят занятия. Своими словами.`}
              rows={5}
              maxLength={4000}
              style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.5 }}
            />
          </div>
          <div style={{ marginTop: 8 }}>
            <Hint>
              <Trans>
                Это первое, что читают. Пара живых предложений работает лучше списка.
              </Trans>
            </Hint>
          </div>

          {asked === null ? null : (
            <>
              <Label>{formatQuestion(asked)}</Label>
              <Segmented
                value={workFormat}
                onChange={setWorkFormat}
                options={formatOptions(asked)}
              />
            </>
          )}

          {asked === null || workFormat === 'online' ? null : (
            <>
              <Label>
                <Trans>Где</Trans>
              </Label>
              <div className={ui.field}>
                <input
                  value={city}
                  onChange={(event) => setCity(event.target.value)}
                  placeholder={t`Город`}
                  maxLength={96}
                  style={{ all: 'unset', width: '100%' }}
                />
              </div>
              <div className={ui.field} style={{ marginTop: 8 }}>
                <input
                  value={placeNote}
                  onChange={(event) => setPlaceNote(event.target.value)}
                  placeholder={t`Район или где удобно встречаться`}
                  maxLength={240}
                  style={{ all: 'unset', width: '100%' }}
                />
              </div>
            </>
          )}

          <Label>
            <Trans>Видимость</Trans>
          </Label>
          {banned ? (
            <div className={ui.ownerLocked}>
              <LockIcon size={18} />
              <span>
                <Trans>Вернуть в каталог может только администратор</Trans>
              </span>
            </div>
          ) : (
            <>
              <Segmented
                value={listed ? 'on' : 'off'}
                onChange={(value) => setListed(value === 'on')}
                options={[
                  { value: 'on', label: <Trans>В каталоге</Trans> },
                  { value: 'off', label: <Trans>Скрыть</Trans> },
                ]}
              />
              <div style={{ marginTop: 9 }}>
                <Hint>
                  {listed ? (
                    <Trans>Тебя видят в поиске и могут написать.</Trans>
                  ) : (
                    <Trans>Анкета сохранится, но в каталоге её не будет.</Trans>
                  )}
                </Hint>
              </div>
            </>
          )}

          <Label>
            <Trans>Новые заявки в Telegram</Trans>
          </Label>
          <Segmented
            value={alerts ? 'on' : 'off'}
            onChange={(value) => setAlerts(value === 'on')}
            options={[
              { value: 'on', label: <Trans>Присылать</Trans> },
              { value: 'off', label: <Trans>Не присылать</Trans> },
            ]}
          />
          <div style={{ marginTop: 9 }}>
            <Hint>
              {alerts ? (
                <Trans>
                  Бот напишет, когда появится заявка по твоей услуге. Не больше 5 в день и
                  не ночью.
                </Trans>
              ) : (
                <Trans>Новые заявки будут только во «Входящих».</Trans>
              )}
            </Hint>
          </div>

          {savedHidden ? (
            <div className={ui.ownerSaved} role="status">
              <Trans>
                Сохранено. Анкета по-прежнему скрыта, администратор посмотрит её ещё раз.
              </Trans>
            </div>
          ) : null}

          {save.isError ? (
            <div style={{ marginTop: 12 }}>
              <Hint>
                <Trans>Не сохранилось — попробуй ещё раз.</Trans>
              </Hint>
            </div>
          ) : null}
        </>
      )}
    </Screen>
  );
}
