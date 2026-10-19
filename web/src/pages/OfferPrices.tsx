import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useMemo, useState } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router';

import { AppHeader } from '@/components/AppHeader';
import { InstitutionPicker } from '@/components/InstitutionPicker';
import { CheckIcon, iconForService } from '@/components/icons';
import { ServiceGroupLabel } from '@/components/Phrase';
import { SubjectSearch } from '@/components/SubjectSearch';
import {
  Chips,
  ChipView,
  Empty,
  Hint,
  Label,
  Screen,
  Segmented,
  SkeletonRows,
  Sub,
  Tile,
  Title,
  ui,
} from '@/components/Ui';
import { hapticSelection, hapticSuccess, useMainButton } from '@/hooks/useTelegram';
import { api } from '@/lib/api';
import { groupRuns } from '@/lib/groups';
import { afterHelperSaved } from '@/lib/helperSaved';
import { type Axis, addAxis, type Draft, dropRow, keyOf } from '@/lib/offerRows';
import { splitNote } from '@/lib/subjectNote';
import { TURNAROUNDS, TurnaroundLabel } from '@/lib/turnaround';
import type {
  Institution,
  MyOffer,
  OfferInput,
  PriceUnit,
  ServiceType,
  Subject,
  WorkFormat,
} from '@/lib/types';
import { askedFormat, formatOptions, formatQuestion } from '@/lib/workFormat';

/**
 * Prices for everything that was ticked, on one screen.
 *
 * One screen and one button, not a form per service. Someone who can do four
 * things should say so once; making them walk a wizard four times is how a
 * catalog ends up full of people who can do one.
 *
 * Nothing here is required. An empty price saves as null, which the catalog
 * already reads as "did not say" rather than as free — and a screen that can be
 * skipped entirely is a screen nobody abandons.
 */
export default function OfferPricesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { t } = useLingui();

  // The choice travels in router state: the two screens are one flow, and a
  // reload legitimately restarts it rather than resuming half way through.
  const picked = (location.state as { picked?: string[] } | null)?.picked;

  const { data: serviceTypes, isError: typesFailed } = useQuery({
    queryKey: ['service-types'],
    queryFn: ({ signal }) => api.getServiceTypes(signal),
    staleTime: 60 * 60 * 1000,
  });

  const {
    data: mine,
    isPending,
    isError: profileFailed,
  } = useQuery({
    queryKey: ['my-helper'],
    queryFn: ({ signal }) => api.getMyHelper(signal),
  });

  const [rows, setRows] = useState<Draft[]>([]);
  const [workFormat, setWorkFormat] = useState<WorkFormat>('both');
  const [loaded, setLoaded] = useState(false);

  // In the catalog's order, not the order the tiles happened to be tapped.
  // The headings below are contiguous runs of the group field, so a person who
  // ticked insurance first and tutoring second would otherwise get «Документы и
  // жизнь» above «Учёба» — and two headings if they went back for a third.
  const chosen = useMemo(() => {
    if (!picked || !serviceTypes) return [];
    const wanted = new Set(picked);
    return serviceTypes.filter((type) => wanted.has(type.code));
  }, [picked, serviceTypes]);

  // Worded by what was actually ticked, not by what the screen is called.
  const asked = useMemo(
    () =>
      askedFormat(
        chosen.map((type) => type.code),
        serviceTypes,
      ),
    [chosen, serviceTypes],
  );

  // Filled once. Whatever the person already offers is carried in, so a save
  // that replaces the whole list does not throw away the prices they set last
  // time.
  useEffect(() => {
    if (!mine || chosen.length === 0 || loaded) return;
    setWorkFormat(mine.work_format);
    setRows(
      chosen.flatMap((type) => {
        const existing = mine.offers.filter((offer) => offer.service_type_id === type.id);
        return existing.length > 0
          ? existing.map((offer) => fromOffer(type, offer))
          : [blank(type)];
      }),
    );
    setLoaded(true);
  }, [mine, chosen, loaded]);

  /*
   * Offers whose service type the catalog no longer lists.
   *
   * `/taxonomy/service-types` returns only active ones, so a type that was
   * deactivated leaves its offers invisible to the grid — and the save below
   * is authoritative, so anything absent from it is deleted. Carried through
   * untouched: withdrawing a category is our decision, and it should not
   * quietly take somebody's row with it the next time they edit a price.
   *
   * The server has to accept them, and now does — `_apply_offers` allows the
   * active types plus whatever the caller already holds. Sending these without
   * that rule would have been worse than the deletion: a 422 on every save,
   * with nothing on screen to say which row was the reason.
   */
  const unlisted = useMemo(() => {
    if (!mine || !serviceTypes) return [];
    const known = new Set(serviceTypes.map((type) => type.id));
    return mine.offers.filter((offer) => !known.has(offer.service_type_id));
  }, [mine, serviceTypes]);

  const save = useMutation({
    mutationFn: () =>
      api.saveHelper({
        // See MyHelper: a question the form did not ask is one the payload does
        // not answer.
        ...(asked === null ? {} : { work_format: workFormat }),
        offers: [...rows.map(toOffer), ...unlisted.map(keep)],
        // Not an unconditional `true`. Somebody who hid their profile on
        // purpose and then adds a service from the cabinet is adding a
        // service, not asking to be listed again — and `false` here keeps a
        // hidden profile hidden rather than un-hiding it behind their back.
        publish: mine?.status !== 'hidden',
      }),
    onSuccess: (me) => {
      hapticSuccess();
      afterHelperSaved(queryClient, me);
      navigate('/my-helper', { replace: true });
    },
  });

  // A hidden profile stays hidden, so the button must not promise otherwise.
  const hidden = mine?.status === 'hidden';

  // Gone once saved: until the navigation lands, the button would otherwise
  // offer «Опубликовать» again and a second tap would publish twice.
  useMainButton(
    loaded && !save.isSuccess
      ? {
          text: hidden ? t`Сохранить` : t`Опубликовать`,
          isVisible: true,
          isEnabled: !save.isPending,
          isLoaderVisible: save.isPending,
          onClick: () => save.mutate(),
        }
      : null,
  );

  // Arrived here directly — a reload, or a link. There is nothing to price.
  if (!picked || picked.length === 0) return <Navigate to="/offer" replace />;

  // What survives a removed chip is `dropRow`'s rule, and it is tested there.
  const removeAxis = (row: Draft, axis: Axis) => {
    setRows((current) => dropRow(current, row, axis));
  };

  // The checklist belongs to the service, not to one of its rows: a person who
  // prepares for ČVUT and for VŠE covers the same things either way. Written to
  // every row of the service so the save carries it whichever rows survive.
  const toggleOption = (type: ServiceType, optionId: number) => {
    hapticSelection();
    setRows((current) => {
      const on = current.some(
        (row) => row.service_type_id === type.id && row.option_ids.includes(optionId),
      );
      return current.map((row) =>
        row.service_type_id === type.id
          ? {
              ...row,
              option_ids: on
                ? row.option_ids.filter((id) => id !== optionId)
                : [...row.option_ids, optionId],
            }
          : row,
      );
    });
  };

  // Like the checklist, this belongs to the service and not to one of its
  // rows, and tapping the chip that is already on clears it back to
  // «договоримся» — a person who mis-taps has no other way back.
  const setTurnaround = (type: ServiceType, days: number) => {
    hapticSelection();
    setRows((current) =>
      current.map((row) =>
        row.service_type_id === type.id
          ? { ...row, turnaround_days: row.turnaround_days === days ? null : days }
          : row,
      ),
    );
  };

  const clearTurnaround = (type: ServiceType) => {
    hapticSelection();
    setRows((current) =>
      current.map((row) =>
        row.service_type_id === type.id ? { ...row, turnaround_days: null } : row,
      ),
    );
  };

  const notePlaceholder = (type: ServiceType) =>
    type.form_shape === 'work'
      ? t`Пара слов о себе — что берёшь и чего не берёшь`
      : t`Пара слов о себе — что делаешь и как быстро`;

  const setNote = (type: ServiceType, note: string) => {
    setRows((current) =>
      current.map((row) => (row.service_type_id === type.id ? { ...row, note } : row)),
    );
  };

  // Which row it lands on, what it inherits and how it is keyed are
  // `addAxis`'s rules, and they are tested there.
  const attach = (
    type: ServiceType,
    axis: Axis,
    picked: { id: number; name: string },
  ) => {
    hapticSelection();
    setRows((current) => addAxis(current, blank(type), axis, picked));
  };

  const addSubject = (type: ServiceType, subject: Subject) =>
    attach(type, 'subject', { id: subject.id, name: subject.name });

  const addInstitution = (type: ServiceType, institution: Institution) =>
    // The server's own `institution.name`, not the short form: a chip that
    // reads ČVUT until the screen reloads and then reads the full name is one
    // school looking like two.
    attach(type, 'institution', { id: institution.id, name: institution.name });

  return (
    <Screen>
      <AppHeader />
      <Title>
        <Trans>Сколько берёшь?</Trans>
      </Title>
      <Sub>
        <Trans>Необязательно. Пустое поле значит «договоримся».</Trans>
      </Sub>

      {typesFailed || profileFailed ? (
        <Empty
          title={<Trans>Не получилось загрузить анкету</Trans>}
          body={<Trans>Проверь связь и попробуй ещё раз.</Trans>}
        />
      ) : isPending || !loaded ? (
        <div style={{ marginTop: 16 }}>
          <SkeletonRows count={4} />
        </div>
      ) : (
        <>
          {groupRuns(chosen, (type) => type.group).map(({ id, value: group, items }) => (
            <div key={id}>
              <Label>
                <ServiceGroupLabel group={group} />
              </Label>
              {items.map((type) => {
                const mineHere = rows.filter((row) => row.service_type_id === type.id);
                const Icon = iconForService(type.code);
                return (
                  // A box each, with the icon and the colour the category wears
                  // everywhere else. Four services under four grey labels read
                  // as one long list of fields belonging to nothing.
                  <div key={type.id} className={ui.svcCard}>
                    <div className={ui.svcHead}>
                      <Tile tone={type.tone}>
                        <Icon size={19} />
                      </Tile>
                      <span className={ui.rowBody}>
                        <span className={ui.rowName}>{type.name}</span>
                        {type.hint ? (
                          <span className={ui.rowHint}>{type.hint}</span>
                        ) : null}
                      </span>
                    </div>

                    <div className={ui.svcBody}>
                      {type.requires_subject ? (
                        <>
                          <AxisChips
                            rows={mineHere.filter((row) => row.subject_id !== null)}
                            label={(row) => row.subject_name}
                            onDrop={(row) => removeAxis(row, 'subject')}
                            removeLabel={t`Убрать`}
                          />
                          <SubjectSearch
                            onPick={(subject) => addSubject(type, subject)}
                            taken={new Set(mineHere.map((row) => row.subject_id))}
                          />
                        </>
                      ) : null}

                      {/* The one service type that declares it needs a school.
                          The flag has been in the database since the grouping
                          and read by nothing, so preparation for ČVUT's
                          entrance exam was stored the same way as preparation
                          for nobody's. */}
                      {type.requires_institution ? (
                        <>
                          <AxisChips
                            rows={mineHere.filter((row) => row.institution_id !== null)}
                            label={(row) => row.institution_name}
                            onDrop={(row) => removeAxis(row, 'institution')}
                            removeLabel={t`Убрать`}
                          />
                          <InstitutionPicker
                            onPick={(institution) => addInstitution(type, institution)}
                            taken={
                              new Set(
                                mineHere
                                  .map((row) => row.institution_id)
                                  .filter((id): id is number => id !== null),
                              )
                            }
                          />
                        </>
                      ) : null}

                      {/* What this errand covers. Reference data rather than
                          free text, because a student can search it and it
                          arrives already translated — the words below the list
                          are for what the list could not say. */}
                      {type.options.length > 0 ? (
                        <div className={ui.ticks}>
                          {type.options.map((option) => {
                            const on = mineHere.some((row) =>
                              row.option_ids.includes(option.id),
                            );
                            return (
                              <button
                                key={option.id}
                                type="button"
                                className={`${ui.tick} ${on ? ui.tickOn : ''}`}
                                aria-pressed={on}
                                onClick={() => toggleOption(type, option.id)}
                              >
                                <span className={ui.tickBox}>
                                  {on ? <CheckIcon size={11} /> : null}
                                </span>
                                {option.label}
                              </button>
                            );
                          })}
                        </div>
                      ) : null}

                      {/* One price per row, not per service. A tutor really
                          does charge 500 for calculus and 700 for physics, and
                          a single field for the pair rewrites both the first
                          time either is touched. The subject names the line
                          when there is more than one. */}
                      {mineHere.map((row) => (
                        <PriceRow
                          key={row.key}
                          // Whichever axis this service has. Two schools would
                          // otherwise be two unlabelled price fields.
                          name={
                            mineHere.length > 1
                              ? (row.subject_name ?? row.institution_name)
                              : null
                          }
                          value={row.price}
                          unit={row.unit}
                          onPrice={(price) =>
                            setRows((current) =>
                              current.map((other) =>
                                other.key === row.key ? { ...other, price } : other,
                              ),
                            )
                          }
                          onUnit={(unit) =>
                            setRows((current) =>
                              current.map((other) =>
                                other.key === row.key ? { ...other, unit } : other,
                              ),
                            )
                          }
                        />
                      ))}
                      {/* Only a written work is asked when. A lesson happens
                          when the two of them agree, and an errand takes as
                          long as the office queue — asking either would be
                          asking somebody to promise the queue. */}
                      {type.form_shape === 'work' ? (
                        <div style={{ marginTop: 4 }}>
                          <Label>
                            <Trans>Срок</Trans>
                          </Label>
                          <Chips>
                            {TURNAROUNDS.map((days) => (
                              <ChipView
                                key={days}
                                active={mineHere[0]?.turnaround_days === days}
                                onClick={() => setTurnaround(type, days)}
                              >
                                <TurnaroundLabel days={days} />
                              </ChipView>
                            ))}
                            {/* Nothing chosen is «договоримся», so the chip is
                                the state rather than a sixth answer: it reads
                                as chosen from the start because it is. */}
                            <ChipView
                              active={mineHere[0]?.turnaround_days == null}
                              onClick={() => clearTurnaround(type)}
                            >
                              <Trans>Договоримся</Trans>
                            </ChipView>
                          </Chips>
                        </div>
                      ) : null}

                      {type.options.length > 0 ? (
                        <div className={`${ui.field} ${ui.fieldTall}`}>
                          <textarea
                            value={mineHere[0]?.note ?? ''}
                            onChange={(event) => setNote(type, event.target.value)}
                            // A written work has just been asked how fast, so
                            // inviting it again in prose asks for the same
                            // answer twice and gets two that disagree.
                            placeholder={notePlaceholder(type)}
                            // The same words as the placeholder, which stops
                            // being the name the moment anything is typed.
                            aria-label={notePlaceholder(type)}
                            rows={3}
                            maxLength={600}
                            style={{
                              all: 'unset',
                              width: '100%',
                              resize: 'none',
                              lineHeight: 1.45,
                            }}
                          />
                        </div>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}

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

          {hidden ? (
            <div style={{ marginTop: 12 }}>
              <Hint>
                <Trans>
                  Анкета скрыта — услуги сохранятся, но в каталоге их не будет. Включить
                  видимость можно в анкете.
                </Trans>
              </Hint>
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
 * One price, and what it is per.
 *
 * The unit belongs to the service rather than to the screen: a profile really
 * does mix them — tutoring by the hour, a thesis by the job — and one control
 * at the top would rewrite "4000 за работу" as "4000 в час".
 */
function PriceRow({
  name,
  value,
  unit,
  onPrice,
  onUnit,
}: {
  /** The subject this price is for, when a service has more than one. */
  name?: string | null;
  value: string;
  unit: PriceUnit;
  onPrice: (price: string) => void;
  onUnit: (unit: PriceUnit) => void;
}) {
  const { t } = useLingui();
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
    // No margin of its own: everything inside a card is spaced by the card.
    <div className={ui.field}>
      {name ? (
        <span
          style={{
            // `flex: none` so the name keeps its width: the input next to it is
            // `flex: 1` and would otherwise squeeze this to two characters and
            // an ellipsis. The cap is what stops a long subject doing the same
            // thing to the input.
            flex: 'none',
            maxWidth: 132,
            color: 'var(--muted)',
            fontSize: 13,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {name}
        </span>
      ) : null}
      <input
        value={value}
        // Digits only, filtered as they are typed. "1 500" and "1,500" both
        // parse to something wrong on a Czech or Russian keyboard, and both
        // save without complaint.
        onChange={(event) => onPrice(event.target.value.replace(/\D/g, '').slice(0, 7))}
        placeholder={t`Сколько`}
        inputMode="numeric"
        aria-label={t`Цена`}
        style={{
          all: 'unset',
          flex: 1,
          minWidth: 0,
          fontVariantNumeric: 'tabular-nums',
        }}
      />
      <span style={{ color: 'var(--muted)', fontSize: 13 }}>Kč</span>
      <select
        value={unit}
        onChange={(event) => onUnit(event.target.value as PriceUnit)}
        aria-label={t`За что цена`}
        style={{
          all: 'unset',
          maxWidth: 104,
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
    </div>
  );
}

/**
 * The rows of one service that already carry an axis, as removable chips.
 *
 * One component for subjects and schools: the two blocks were byte-identical
 * apart from the field they read and the axis they name when a chip goes.
 */
function AxisChips({
  rows,
  label,
  onDrop,
  removeLabel,
}: {
  rows: Draft[];
  label: (row: Draft) => string | null;
  onDrop: (row: Draft) => void;
  removeLabel: string;
}) {
  if (!rows.length) return null;
  return (
    <Chips>
      {rows.map((row) => (
        <ChipView
          key={row.key}
          active
          removeLabel={removeLabel}
          onRemove={() => onDrop(row)}
        >
          <ChipText label={label(row) ?? ''} />
        </ChipView>
      ))}
    </Chips>
  );
}

/** A long name wraps inside its chip; the note in brackets reads lighter. */
function ChipText({ label }: { label: string }) {
  const { name, note } = splitNote(label);
  return (
    <span className={ui.chipText}>
      {name}
      {note ? <span className={ui.chipNote}> ({note})</span> : null}
    </span>
  );
}

function blank(type: ServiceType): Draft {
  const row: Draft = {
    key: '',
    service_type_id: type.id,
    subject_id: null,
    subject_name: null,
    institution_id: null,
    institution_name: null,
    option_ids: [],
    note: '',
    turnaround_days: null,
    price: '',
    // From the server, not guessed here: a thesis priced by the hour reads as
    // ten times too little.
    unit: type.default_price_unit ?? 'hour',
    langs: [],
  };
  // Keyed like every other row, from its axes — see `keyOf`.
  return { ...row, key: keyOf(row) };
}

function fromOffer(type: ServiceType, offer: MyOffer): Draft {
  const row: Draft = {
    key: '',
    service_type_id: offer.service_type_id,
    subject_id: offer.subject_id,
    subject_name: offer.subject_name,
    institution_id: offer.institution_id,
    institution_name: offer.institution_name,
    option_ids: offer.option_ids,
    note: offer.note ?? '',
    turnaround_days: offer.turnaround_days,
    // Rounded, because the field holds digits: an older row saved as 550.5
    // would render a decimal point the input then refuses to accept.
    price: offer.price_amount == null ? '' : String(Math.round(offer.price_amount)),
    unit: offer.price_unit ?? type.default_price_unit ?? 'hour',
    langs: offer.langs,
  };
  return { ...row, key: keyOf(row) };
}

/** An offer we are not editing, sent back exactly as it came. */
function keep(offer: MyOffer): OfferInput {
  return {
    service_type_id: offer.service_type_id,
    subject_id: offer.subject_id,
    institution_id: offer.institution_id,
    price_amount: offer.price_amount,
    price_unit: offer.price_unit,
    langs: offer.langs,
    option_ids: offer.option_ids,
    note: offer.note,
    turnaround_days: offer.turnaround_days,
  };
}

function toOffer(row: Draft): OfferInput {
  return {
    service_type_id: row.service_type_id,
    subject_id: row.subject_id,
    institution_id: row.institution_id,
    // The field holds digits and nothing else, so there is no parse to get
    // wrong. Empty means "did not say", not free.
    price_amount: row.price ? Number(row.price) : null,
    price_unit: row.unit,
    langs: row.langs,
    option_ids: row.option_ids,
    note: row.note.trim() || null,
    turnaround_days: row.turnaround_days,
  };
}
