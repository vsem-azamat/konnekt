import { Trans, useLingui } from '@lingui/react/macro';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useNavigate } from 'react-router';

import { hapticSelection, hapticSuccess } from '@/hooks/useTelegram';
import { ApiError, api } from '@/lib/api';
import { chipKey, chipLabel } from '@/lib/chips';
import { REQUEST_CITIES, requestPlace, spelledCity } from '@/lib/requestPlace';
import type { Chip, RequestCreate, WorkFormat } from '@/lib/types';
import { CityName, useCityNames } from './Place';
import { Sheet } from './Sheet';
import { Action, Chips, ChipView, Hint, Label, Segmented, ui } from './Ui';

/**
 * Which axis each kind of chip is.
 *
 * Only the four the search filters on, and only the ones whose value is a
 * number: a deadline is neither, which is why the sheet has no chip for it.
 */
const AXIS = {
  subject: 'subject_id',
  institution: 'institution_id',
  service_type: 'service_type_id',
  budget: 'budget_max',
} as const satisfies Record<string, keyof RequestCreate>;

/** Every axis the payload speaks about, chip or no chip. */
const AXES = Object.values(AXIS);

/**
 * Turn the search that is already on screen into a request.
 *
 * Nothing here is a new form. The words are the ones the person typed, the
 * chips are the ones the search is already filtering on, and the only decision
 * left is which of them the request should carry — a tutor for this subject at
 * any school is an ordinary thing to want, and removing the school chip is how
 * you say it.
 *
 * A removed chip is sent as an explicit `null` rather than left out. The server
 * reads anything the caller did not mention out of the text, so leaving it out
 * would put the school straight back — see `services/requests.create`.
 *
 * The deadline is not among the chips: it is not a filter, so the search never
 * carried one. It still reaches the request, because the server reads the text,
 * and the words are right there to edit.
 */
export function RequestSheet({
  text,
  chips,
  known,
  onClose,
}: {
  text: string;
  chips: Chip[];
  /**
   * Whether `chips` is the search's answer or merely what we have so far.
   *
   * An empty list means two different things — the search found nothing to
   * filter on, or it has not come back — and the second one must not be read
   * as "no subject, no school, no kind of help".
   */
  known: boolean;
  onClose: () => void;
}) {
  const { t, i18n } = useLingui();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [words, setWords] = useState(text);
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  // Empty string is "not asked for" and not zero: the field only exists once
  // somebody taps the chip that adds it.
  const [budget, setBudget] = useState<string | null>(null);
  // What «Входящие» narrows by, so asked outright: the words never set it.
  const [format, setFormat] = useState<WorkFormat>('both');
  const [city, setCity] = useState<string>(REQUEST_CITIES[0]);
  // Kept apart from the chips, so a look at «Прага» does not lose what was typed.
  const [otherCity, setOtherCity] = useState(false);
  const [typedCity, setTypedCity] = useState('');
  const cityNames = useCityNames();

  const hasBudget = chips.some((chip) => chip.kind === 'budget');

  const post = useMutation({
    mutationFn: () => api.createRequest(payload()),
    onSuccess: () => {
      hapticSuccess();
      void queryClient.invalidateQueries({ queryKey: ['requests'] });
      navigate('/mine');
    },
  });

  /**
   * The chips describe the sentence that produced them.
   *
   * Which is only true while the sentence is the one the search ran. Three of
   * the four ways onto `/results` carry no words at all — a tile on the home
   * screen, a category from the profile — and there the person writes the
   * sentence here, from scratch; edit the words and the same thing is true.
   */
  const fromSearch = known && text.trim().length > 0 && words.trim() === text.trim();

  function payload(): RequestCreate {
    // Every axis is mentioned when the chips still describe these words: an
    // axis missing from the search is one the person took off on `/ask`, or
    // one the parser never found, and either way the server must not put it
    // back out of the text. Silence would mean exactly that, which is the case
    // this whole change is about.
    //
    // When the words are new, silence is right for an axis nobody touched: the
    // sentence is the only thing that knows what it is about. Removals are
    // sent either way, just below. The deadline is unmentioned in every case —
    // it is not a filter, so the words are the only place it can come from.
    const body: RequestCreate = { text: words.trim() };
    if (fromSearch) for (const axis of AXES) body[axis] = null;
    for (const chip of chips) {
      const axis = AXIS[chip.kind as keyof typeof AXIS];
      if (!axis || chip.value == null) continue;
      // A chip taken off is a removal whatever happened to the words: the
      // screen shows it as gone, so the request must not carry it, and only an
      // explicit null says that. Editing the sentence changes what silence
      // means, never what a removal means.
      body[axis] = dropped.has(chipKey(chip)) ? null : Number(chip.value);
    }
    if (budget) body.budget_max = Number(budget);
    const place = otherCity ? spelledCity(typedCity, cityNames) : city;
    return { ...body, ...requestPlace(format, place) };
  }

  // «Другой…» left empty would post a request in no city, which every city
  // chip in «Входящие» then leaves out: in person is exactly where it counts.
  const placed = format === 'online' || !otherCity || typedCity.trim().length > 0;
  const enough = words.trim().length >= 3 && placed;

  return (
    <Sheet title={<Trans>Что нужно</Trans>} onClose={onClose} closeLabel={t`Закрыть`}>
      <div className={`${ui.field} ${ui.fieldTall}`}>
        <textarea
          value={words}
          onChange={(event) => setWords(event.target.value)}
          aria-label={t`Что нужно`}
          rows={2}
          maxLength={2000}
          style={{ all: 'unset', width: '100%', resize: 'none', lineHeight: 1.45 }}
        />
      </div>

      <Chips>
        {chips.map((chip) => {
          const key = chipKey(chip);
          const isDropped = dropped.has(key);
          return (
            <ChipView
              key={key}
              active={!isDropped}
              ghost={isDropped}
              removeLabel={t`Убрать`}
              onRemove={
                isDropped
                  ? undefined
                  : () => {
                      hapticSelection();
                      setDropped(new Set(dropped).add(key));
                    }
              }
              onClick={
                isDropped
                  ? () => {
                      const next = new Set(dropped);
                      next.delete(key);
                      setDropped(next);
                    }
                  : undefined
              }
            >
              {chipLabel(chip, i18n.locale)}
            </ChipView>
          );
        })}
        {/* Only when the sentence carried none. A budget is the one thing
            people leave out of the words and mean anyway. */}
        {!hasBudget && budget === null ? (
          <ChipView
            ghost
            onClick={() => {
              hapticSelection();
              setBudget('');
            }}
          >
            <Trans>+ бюджет</Trans>
          </ChipView>
        ) : null}
      </Chips>

      {budget !== null ? (
        <div className={ui.field}>
          <input
            value={budget}
            // Six digits, not the seven the price fields allow: the server
            // bounds a budget at a million, and a number it will refuse is one
            // the person only finds out about through a failed save.
            onChange={(event) =>
              setBudget(event.target.value.replace(/\D/g, '').slice(0, 6))
            }
            inputMode="numeric"
            placeholder={t`Сколько готов платить`}
            aria-label={t`Сколько готов платить`}
            style={{ all: 'unset', width: '100%' }}
          />
          <span style={{ color: 'var(--muted)', fontSize: 13 }}>Kč</span>
        </div>
      ) : null}

      <Label>
        <Trans>Как удобно</Trans>
      </Label>
      <Segmented
        value={format}
        label={t`Как удобно`}
        onChange={(value) => {
          hapticSelection();
          setFormat(value);
        }}
        options={[
          { value: 'both', label: <Trans>Неважно</Trans> },
          { value: 'online', label: <Trans>Онлайн</Trans> },
          { value: 'offline', label: <Trans>Лично</Trans> },
        ]}
      />

      {format === 'online' ? null : (
        <>
          <Label>
            <Trans>Город</Trans>
          </Label>
          <Chips>
            {REQUEST_CITIES.map((name) => {
              const on = !otherCity && city === name;
              return (
                <ChipView
                  key={name}
                  active={on}
                  pressed={on}
                  onClick={() => {
                    hapticSelection();
                    setOtherCity(false);
                    setCity(name);
                  }}
                >
                  <CityName city={name} />
                </ChipView>
              );
            })}
            <ChipView
              active={otherCity}
              pressed={otherCity}
              onClick={() => {
                if (otherCity) return;
                hapticSelection();
                setOtherCity(true);
              }}
            >
              <Trans>Другой…</Trans>
            </ChipView>
          </Chips>
          {otherCity ? (
            <div className={ui.field} style={{ marginTop: 8 }}>
              <input
                value={typedCity}
                onChange={(event) => setTypedCity(event.target.value)}
                placeholder={t`Город`}
                aria-label={t`Город`}
                maxLength={96}
                style={{ all: 'unset', width: '100%' }}
              />
            </div>
          ) : null}
        </>
      )}

      {post.isError ? (
        <Hint>
          <PostError error={post.error} />
        </Hint>
      ) : (
        <Hint>
          <Trans>
            Заявку увидят все, кто предлагает помощь. Дату из текста поймём сами.
          </Trans>
        </Hint>
      )}

      <Action disabled={!enough || post.isPending} onClick={() => post.mutate()}>
        <Trans>Опубликовать заявку</Trans>
      </Action>
    </Sheet>
  );
}

/**
 * Why it did not post.
 *
 * The 409 is the one worth naming: "try again" invites a retry that cannot
 * succeed while the earlier request is open, and the person would keep tapping.
 */
function PostError({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.status === 409) {
    return <Trans>Такая заявка уже открыта — она в разделе «Заявки»</Trans>;
  }
  return <Trans>Не отправилось — попробуй ещё раз.</Trans>;
}
