/**
 * Sentences the server asked for, rendered here.
 *
 * The API sends a code and parameters rather than finished text — `{"code":
 * "reason.same_exam_experience", "params": {"deals": 38}}` — because Czech has
 * four plural forms, Russian's are shaped differently, and getting that right
 * needs the plural rules, which live in the client. A backend that shipped
 * finished sentences would have to reimplement CLDR to say "38 человек".
 *
 * An unknown code renders nothing. New codes appear on the server before they
 * appear here, and a missing line is better than a raw identifier on screen.
 */

import { Plural, Trans } from '@lingui/react/macro';
import type { ReactElement } from 'react';

import type { Phrase as PhraseData, ServiceGroup } from '@/lib/types';

function num(value: unknown): number {
  return typeof value === 'number' ? value : Number(value ?? 0);
}

function str(value: unknown): string {
  return typeof value === 'string' ? value : String(value ?? '');
}

/** A date the server sent as YYYY-MM-DD, in the reader's locale. */
export function formatDay(iso: string, locale: string): string {
  const date = new Date(`${iso}T00:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long' }).format(date);
}

export function PhraseView({
  phrase,
  locale,
}: {
  phrase: PhraseData | null | undefined;
  locale: string;
}): ReactElement | null {
  if (!phrase) return null;
  const p = phrase.params ?? {};

  switch (phrase.code) {
    case 'reason.same_exam_experience':
      return (
        <Plural
          value={num(p.deals)}
          one="Опыт с этим экзаменом: # человек"
          few="Опыт с этим экзаменом: # человека"
          many="Опыт с этим экзаменом: # человек"
          other="Опыт с этим экзаменом: # человека"
        />
      );
    case 'reason.same_institution':
      return <Trans>Работает именно с этим вузом</Trans>;
    case 'reason.cheapest_but_unproven':
      return <Trans>Дешевле остальных, но опыта с этим экзаменом пока нет</Trans>;
    case 'reason.subject_only':
      return <Trans>Ведёт предмет, но без привязки к этому вузу</Trans>;
    case 'reason.your_faculty':
      return <Trans>С твоего факультета</Trans>;
    case 'feed.same_subject':
      return <Trans>Твой предмет: {str(p.subject)}</Trans>;
    case 'feed.same_institution':
      return <Trans>Вуз, с которым ты работаешь</Trans>;
    case 'feed.same_service':
      return <Trans>То, чем ты занимаешься</Trans>;
    case 'reason.experience':
      return (
        <Plural
          value={num(p.deals)}
          one="# занятие через нас"
          few="# занятия через нас"
          many="# занятий через нас"
          other="# занятия через нас"
        />
      );
    case 'availability.free_on': {
      const day = formatDay(str(p.date), locale);
      return <Trans>Есть время {day}</Trans>;
    }
    case 'availability.responds_in':
      return (
        <Plural
          value={num(p.minutes)}
          one="Отвечает примерно за # минуту"
          few="Отвечает примерно за # минуты"
          many="Отвечает примерно за # минут"
          other="Отвечает примерно за # минуты"
        />
      );
    case 'parse.nothing_recognised':
      return (
        <Trans>
          Не получилось разобрать запрос. Попробуй назвать предмет — «математический
          анализ», «čeština B2», «физика».
        </Trans>
      );
    case 'clarify.when':
      return <Trans>Помощь нужна до экзамена или на нём?</Trans>;
    default:
      return null;
  }
}

/** Labels for the answers to a clarifying question. */
export function ClarifyOptionLabel({ code }: { code: string }): ReactElement | null {
  switch (code) {
    case 'exam_prep':
      return <Trans>Разобраться заранее</Trans>;
    case 'exam_live_help':
      return <Trans>Помощь в день экзамена</Trans>;
    case 'both':
      return <Trans>И то, и другое</Trans>;
    default:
      return null;
  }
}

/** The little captions under the numbers on a profile. */
export function StatLabel({
  code,
  value,
}: {
  code: string;
  value: string;
}): ReactElement | null {
  switch (code) {
    // The caption sits under the number, so it is the noun alone and has to
    // agree with it: "1 год", "3 года", "5 лет".
    case 'stat.deals':
      return (
        <Plural
          value={Number(value)}
          one="занятие через нас"
          few="занятия через нас"
          many="занятий через нас"
          other="занятия через нас"
        />
      );
    case 'stat.years':
      return (
        <Plural
          value={Number(value)}
          one="год на площадке"
          few="года на площадке"
          many="лет на площадке"
          other="года на площадке"
        />
      );
    case 'stat.since':
      return <Trans>первый год</Trans>;
    default:
      return null;
  }
}

/** How a price is charged: per hour, per lesson, per piece of work. */
export function PriceUnitLabel({ unit }: { unit: string }): ReactElement {
  switch (unit) {
    case 'lesson':
      return <Trans>за занятие</Trans>;
    case 'work':
      return <Trans>за работу</Trans>;
    case 'day':
      return <Trans>в день</Trans>;
    case 'week':
      return <Trans>за неделю</Trans>;
    case 'month':
      return <Trans>в месяц</Trans>;
    case 'semester':
      return <Trans>за семестр</Trans>;
    case 'item':
      return <Trans>за штуку</Trans>;
    case 'negotiable':
      return <Trans>договорная</Trans>;
    default:
      return <Trans>за час</Trans>;
  }
}

/**
 * The heading over a shelf of service tiles.
 *
 * Translated here rather than in the database, like every other closed enum
 * the server sends. See catalog/docs/data-model.md — the i18n tables are for rows we
 * keep adding to, and there are three of these for good.
 */
export function ServiceGroupLabel({ group }: { group: ServiceGroup }): ReactElement {
  switch (group) {
    case 'study':
      return <Trans>Учёба</Trans>;
    case 'entrance':
      return <Trans>Экзамены и поступление</Trans>;
    case 'life':
      return <Trans>Документы и жизнь</Trans>;
  }
}

/** Online, in person, or either. */
export function WorkFormatLabel({ format }: { format: string }): ReactElement {
  switch (format) {
    case 'online':
      return <Trans>Онлайн</Trans>;
    case 'offline':
      return <Trans>Очно</Trans>;
    default:
      return <Trans>Онлайн и очно</Trans>;
  }
}
