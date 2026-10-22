import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { HideReasonText } from '@/components/HideReasonText';
import { CloseIcon, LockIcon, PlusIcon } from '@/components/icons';
import {
  Empty,
  Hint,
  Label,
  Row,
  Rows,
  Screen,
  Segmented,
  SkeletonRows,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { afterHelperSaved } from '@/lib/helperSaved';
import { type OwnerStatus, ownerStatus, startsListed } from '@/lib/ownerStatus';
import type { MyHelper, MyOffer, OfferInput, PriceUnit, WorkFormat } from '@/lib/types';
import { askedFormat, formatOptions, formatQuestion } from '@/lib/workFormat';

/**
 * The helper's own page: everything they have told us, editable.
 *
 * One screen, not a wizard. Someone who has already decided to help should be
 * able to fix a price in ten seconds, and every step between them and that is a
 * step where they close the app instead. Nothing here is required — an empty
 * profile is a profile nobody finds, which is a fair consequence and not an
 * error message.
 *
 * Adding a service is the one thing that leaves: it goes to `/offer`, the same
 * grid used when the person first joined. What used to be here was a subject
 * search that attached everything it found to tutoring, so somebody who writes
 * theses or fills in residence forms could not add what they actually do.
 */
export default function MyHelperPage() {
  const navigate = useNavigate();
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
  const [rows, setRows] = useState<Draft[]>([]);
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

  // Worded by what is on the screen now, not by what the server last saw:
  // deleting the last lesson row has to stop the question asking about
  // teaching before the profile is refetched.
  //
  // Until the reference list is here — still loading, or failed — the neutral
  // wording rather than nothing. Otherwise the question and the whole city
  // block are missing from a screen that already renders a live Save button,
  // and then appear: on a cold cache as a flicker, on a failure for ever, with
  // the person never learning a question existed.
  const asked = useMemo(
    () =>
      askedFormat(
        rows.map((row) => row.code),
        serviceTypes,
      ),
    [serviceTypes, rows],
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
    setRows(data.offers.map(toDraft));
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
        offers: rows.map(toOffer),
        publish: listed,
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
        <Trans>Моя анкета</Trans>
      </Title>
      {seen && status ? (
        <StatusCard status={status} helper={seen} listed={listed} />
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

          <Label>
            <Trans>Мои услуги</Trans>
          </Label>

          {rows.length === 0 ? (
            <Hint>
              <Trans>
                Пока ни одной. Добавь ниже — без них тебя не найдут по поиску.
              </Trans>
            </Hint>
          ) : (
            <Rows>
              {rows.map((row) => (
                <SubjectRow
                  key={row.key}
                  row={row}
                  onPrice={(price) =>
                    setRows(rows.map((r) => (r.key === row.key ? { ...r, price } : r)))
                  }
                  onUnit={(next) =>
                    setRows(
                      rows.map((r) => (r.key === row.key ? { ...r, unit: next } : r)),
                    )
                  }
                  onRemove={() => setRows(rows.filter((r) => r.key !== row.key))}
                />
              ))}
            </Rows>
          )}

          {/* Adding goes through the same grid the offer flow uses. The box
              that used to be here searched subjects and attached every one of
              them to tutoring, so a person who wrote theses could not add that
              at all. */}
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
            </Rows>
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

/**
 * Where the profile stands, and who can change that: the owner's own states,
 * «на проверке» (listed already, only not looked at yet), and an operator's
 * hide with its reason.
 */
function StatusCard({
  status,
  helper,
  listed,
}: {
  status: OwnerStatus;
  helper: MyHelper;
  /** «Видимость» below as it is now, which the draft's hint talks about. */
  listed: boolean;
}) {
  return (
    <div className={ui.ownerStatus} data-status={status}>
      <span className={ui.ownerStatusTitle}>
        {status === 'draft' ? (
          <Trans>Черновик</Trans>
        ) : status === 'review' ? (
          <Trans>На проверке</Trans>
        ) : status === 'listed' ? (
          <Trans>В каталоге</Trans>
        ) : status === 'hidden' ? (
          <Trans>Скрыта тобой</Trans>
        ) : (
          <Trans>Скрыта администратором</Trans>
        )}
      </span>
      {status === 'banned' && helper.hidden_reason ? (
        <span>
          {helper.hidden_reason === 'other' && helper.hidden_note ? (
            <Trans>Причина: {helper.hidden_note}</Trans>
          ) : (
            <Trans>
              Причина: <HideReasonText reason={helper.hidden_reason} />
            </Trans>
          )}
        </span>
      ) : null}
      <span>
        {status === 'draft' ? (
          // A new profile starts on «В каталоге» (startsListed), so the hint
          // says what saving does rather than ask for a choice already made.
          listed ? (
            <Trans>
              Пока её видишь только ты. Ниже уже стоит «В каталоге»: нажми «Сохранить», и
              анкета появится в поиске.
            </Trans>
          ) : (
            <Trans>
              Пока её видишь только ты. Выбери «В каталоге», когда всё готово.
            </Trans>
          )
        ) : status === 'review' ? (
          <Trans>Анкета уже в каталоге, администратор её ещё не смотрел.</Trans>
        ) : status === 'listed' ? (
          <Trans>Тебя видят в поиске и могут написать.</Trans>
        ) : status === 'hidden' ? (
          <Trans>Анкета сохранена, но в каталоге её нет. Вернуть можно ниже.</Trans>
        ) : helper.under_review ? (
          <Trans>
            В каталоге её не видно. Правки сохранены, администратор посмотрит анкету ещё
            раз.
          </Trans>
        ) : (
          <Trans>
            В каталоге её не видно. Править анкету можно, правки сохранятся, но вернуть её
            в каталог может только администратор.
          </Trans>
        )}
      </span>
    </div>
  );
}

/**
 * One thing this person offers: its price, what the price is per, and the way
 * to drop it.
 *
 * The unit lives on the row rather than on the screen. A profile really can
 * mix them — tutoring by the hour, a thesis by the job — and a single control
 * at the top would quietly rewrite "1500 за работу" as "1500 в час" the first
 * time anything else on the page was saved.
 */
function SubjectRow({
  row,
  onPrice,
  onUnit,
  onRemove,
}: {
  row: Draft;
  onPrice: (price: string) => void;
  onUnit: (unit: PriceUnit) => void;
  onRemove: () => void;
}) {
  const { t } = useLingui();
  /*
   * A native select: it shows what the alternatives are, opens the platform's
   * own picker on a phone, and follows `color-scheme` in both themes.
   *
   * Every unit, not the popular four. A select whose value is missing from its
   * options renders the first one instead, so a profile priced per semester
   * would show "за час" and be saved that way the next time anything else on
   * the page changed.
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
    <div className={ui.row}>
      <span className={ui.rowBody}>
        {/* A service with no subject — writing a thesis, nostrification — is
            named by what it is, not by the blank where a subject would go. */}
        <span className={ui.rowName}>{row.subject_name ?? row.service_type_name}</span>
        {row.institution_name ? (
          <span className={ui.rowHint}>{row.institution_name}</span>
        ) : null}
      </span>
      <input
        value={row.price}
        /*
         * Digits only, filtered as they are typed.
         *
         * Prices here are whole crowns, and parsing free text was a way to be
         * quietly wrong in two directions at once: "1,500" became 1.5 Kč,
         * because a comma is a decimal point on a Czech or Russian keyboard,
         * and "1 500" became nothing at all. Both saved without complaint and
         * left the field still showing what the person had typed. Refusing
         * the characters is the version with no failure mode to explain.
         */
        onChange={(event) => onPrice(event.target.value.replace(/\D/g, '').slice(0, 7))}
        placeholder={t`Kč`}
        inputMode="numeric"
        aria-label={t`Цена`}
        style={{
          all: 'unset',
          width: 52,
          textAlign: 'right',
          fontVariantNumeric: 'tabular-nums',
        }}
      />
      {/* The currency stays once a price is typed: the placeholder alone
          left a bare «600 за час». */}
      {row.price !== '' ? (
        <span style={{ marginLeft: -6, fontSize: 15, color: 'var(--ink)' }}>Kč</span>
      ) : null}
      <select
        value={row.unit}
        onChange={(event) => onUnit(event.target.value as PriceUnit)}
        aria-label={t`За что цена`}
        style={{
          all: 'unset',
          maxWidth: 92,
          fontSize: 12,
          color: 'var(--muted)',
          cursor: 'pointer',
        }}
      >
        {units.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <button
        type="button"
        className={`${ui.chipRemove} ${ui.rowRemove}`}
        aria-label={t`Убрать`}
        onClick={onRemove}
      >
        <CloseIcon size={14} />
      </button>
    </div>
  );
}

/**
 * An offer while it is being edited.
 *
 * The price is a string, not a number: an input mid-typing legitimately holds
 * "" and "4", and parsing on every keystroke turns both into something the
 * field then has to render back.
 */
interface Draft {
  key: string;
  service_type_id: number;
  /** The service type's `code`, which is what the reference list is keyed by. */
  code: string;
  service_type_name: string;
  subject_id: number | null;
  subject_name: string | null;
  institution_id: number | null;
  institution_name: string | null;
  option_ids: number[];
  note: string | null;
  turnaround_days: number | null;
  price: string;
  unit: PriceUnit;
  langs: string[];
}

function toDraft(offer: MyOffer): Draft {
  return {
    // The subject alone is not unique — the same subject at two schools is two
    // rows — so the key carries every axis the server keys on.
    key: `${offer.service_type_id}:${offer.subject_id}:${offer.institution_id}`,
    service_type_id: offer.service_type_id,
    code: offer.service_type,
    service_type_name: offer.service_type_name,
    subject_id: offer.subject_id,
    subject_name: offer.subject_name,
    institution_id: offer.institution_id,
    institution_name: offer.institution_name,
    option_ids: offer.option_ids,
    note: offer.note,
    turnaround_days: offer.turnaround_days,
    // Rounded, because the field holds digits: an older row saved as 550.5
    // would otherwise render a decimal point the input then refuses to accept.
    price: offer.price_amount == null ? '' : String(Math.round(offer.price_amount)),
    unit: offer.price_unit,
    langs: offer.langs,
  };
}

function toOffer(row: Draft): OfferInput {
  return {
    service_type_id: row.service_type_id,
    subject_id: row.subject_id,
    institution_id: row.institution_id,
    // The field holds digits and nothing else, so there is no parse to get
    // wrong. An empty one means "did not say", not free.
    price_amount: row.price ? Number(row.price) : null,
    price_unit: row.unit,
    langs: row.langs,
    // Carried straight back: this screen edits neither the checklist nor the
    // turnaround, and the server would keep both anyway, but sending what we
    // hold means one save never depends on the other end remembering.
    option_ids: row.option_ids,
    note: row.note,
    turnaround_days: row.turnaround_days,
  };
}
