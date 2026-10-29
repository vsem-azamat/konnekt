/**
 * The rows behind the prices screen, and the one rule that is not obvious.
 *
 * Here rather than in the page because it is behaviour and not layout: what
 * survives when a row goes is a decision about somebody's saved answers, and a
 * decision like that should be provable without rendering a screen.
 */

import type { PriceUnit } from './types';

/**
 * One offer while it is being edited. The price is a string: an input
 * mid-typing legitimately holds "" and "4", and parsing on every keystroke
 * turns both into something the field then has to render back.
 */
export interface Draft {
  key: string;
  service_type_id: number;
  subject_id: number | null;
  subject_name: string | null;
  institution_id: number | null;
  institution_name: string | null;
  option_ids: number[];
  note: string;
  // `null` is «договоримся», which is an answer, so the field is never absent.
  turnaround_days: number | null;
  price: string;
  unit: PriceUnit;
  langs: string[];
}

/**
 * What a new row of a service starts from.
 *
 * A second subject added to a service inherits what the person already said
 * about that service, for the reason the screen writes a toggled option to
 * every row: asking the same price four times is asking three times too many,
 * and a row added after the ticks were set would otherwise save an empty
 * checklist. Empty when the service has no row yet.
 */
export function serviceAnswers(rows: Draft[], serviceTypeId: number): Partial<Draft> {
  const sibling = rows.find((row) => row.service_type_id === serviceTypeId);
  if (!sibling) return {};
  const { price, unit, option_ids, note, turnaround_days } = sibling;
  return { price, unit, option_ids, note, turnaround_days };
}

/** The two axes a row can carry. `offers` is unique on both of them. */
export type Axis = 'subject' | 'institution';

const without = (row: Draft, axis: Axis): Draft =>
  axis === 'subject'
    ? { ...row, subject_id: null, subject_name: null }
    : { ...row, institution_id: null, institution_name: null };

/**
 * The rows left after one axis chip is removed.
 *
 * The tapped chip is the whole of what is being taken back, and two things
 * follow from that.
 *
 * One row can carry both axes — a school picked first and a subject after it
 * fill the same row — and it appears in both chip lists. Removing the subject
 * there leaves the school, rather than taking a school the person never touched.
 *
 * And a service whose last axis goes keeps its row, because the person ticked
 * the service: one with no axis is a service search cannot reach yet, not one
 * they withdrew. The row keeps everything else it held — the checklist, the
 * note and the turnaround belong to the service type and not to one of its
 * rows, which is what `catalog/docs/data-model.md` says of those columns and why the
 * screen writes a toggled option to every row of a service. A fresh blank row
 * here would answer «I do these five things, in three days, for 500» with
 * silence, because a chip was tapped off.
 */
export function dropRow(rows: Draft[], row: Draft, axis: Axis): Draft[] {
  const left = without(row, axis);
  const others = rows.filter((other) => other.key !== row.key);
  const siblings = others.filter(
    (other) => other.service_type_id === row.service_type_id,
  );
  const bare = left.subject_id === null && left.institution_id === null;
  // Gone, in the two cases where keeping it would say nothing new: a row with
  // no axis left beside a row that has one, and a row whose remaining axis
  // another row of the service already names — that pair is one offer, and the
  // server's unique index says so.
  if (
    bare ? siblings.length > 0 : siblings.some((other) => keyOf(other) === keyOf(left))
  ) {
    return others;
  }
  // Otherwise in place, so the row keeps its position among its neighbours, and
  // re-keyed from what it now holds: a key naming an axis the row no longer has
  // is one `addAxis` could mint a second time.
  return rows.map((other) =>
    other.key === row.key ? { ...left, key: keyOf(left) } : other,
  );
}

/**
 * A row's key, from its axes — the same pair `offers` is unique on, so two rows
 * of one service that agree on it are one offer.
 *
 * Every row that exists is keyed through here, which is what makes the key
 * readable as the row's identity: a key minted once and left alone while the
 * row's axes change is a key that can be minted again for a different row, and
 * two rows sharing one would share a price field and save as a duplicate.
 * `dropRow` keeps the other half of it — a clearing that would produce a key
 * the service already has drops the row instead of minting a twin.
 */
export function keyOf(row: Draft): string {
  return `${row.service_type_id}:${row.subject_id}:${row.institution_id}`;
}

/**
 * Attach a subject or a school to a service.
 *
 * One function for both, because they are the same move: `offers` is unique on
 * its axes, so calculus and physics — or ČVUT and VŠE — are two rows of the
 * same service, and the first row of a service that takes an axis starts
 * without one.
 *
 * That first row is filled rather than left behind, which would otherwise save
 * as "this service, no subject" beside the real ones. A row that is added
 * instead starts from `serviceAnswers`.
 *
 * The axis is named rather than read off the fields being set, so a caller
 * that names neither is a type error instead of a row filled with nothing.
 */
export function addAxis(
  rows: Draft[],
  blank: Draft,
  axis: Axis,
  picked: { id: number; name: string },
): Draft[] {
  const service = blank.service_type_id;
  const named: Partial<Draft> =
    axis === 'subject'
      ? { subject_id: picked.id, subject_name: picked.name }
      : { institution_id: picked.id, institution_name: picked.name };
  const holds: keyof Draft = axis === 'subject' ? 'subject_id' : 'institution_id';
  const empty = rows.find(
    (row) => row.service_type_id === service && row[holds] === null,
  );
  if (empty) {
    return rows.map((row) =>
      row === empty ? { ...row, ...named, key: keyOf({ ...row, ...named }) } : row,
    );
  }
  const added = { ...blank, ...serviceAnswers(rows, service), ...named };
  return [...rows, { ...added, key: keyOf(added) }];
}

/**
 * A price chip, applied to one service's rows.
 *
 * One price per row, as the field is: a tutor who charges 500 for calculus
 * and 700 for physics keeps both. So a chip writes to every row only while
 * they agree (or are all still empty, the first time somebody prices the
 * service) and otherwise only to the rows that have no price yet.
 */
export function applyPriceChip(
  rows: Draft[],
  serviceTypeId: number,
  price: string,
  unit: PriceUnit,
): Draft[] {
  const mine = rows.filter((row) => row.service_type_id === serviceTypeId);
  const agree = mine.every(
    (row) => row.price === mine[0]?.price && row.unit === mine[0]?.unit,
  );
  return rows.map((row) =>
    row.service_type_id === serviceTypeId && (agree || row.price === '')
      ? { ...row, price, unit }
      : row,
  );
}

/**
 * Whether a chip reads as chosen: only when every row of the service says
 * it. «договоримся» (`price` empty) is chosen while nothing is priced, which
 * is what the screen promises an empty field means.
 */
export function priceChipOn(
  rows: Draft[],
  serviceTypeId: number,
  price: string,
  unit: PriceUnit,
): boolean {
  const mine = rows.filter((row) => row.service_type_id === serviceTypeId);
  if (mine.length === 0) return false;
  if (price === '') return mine.every((row) => row.price === '');
  return mine.every((row) => row.price === price && row.unit === unit);
}

/**
 * A price typed after «договоримся»: back to a unit a number can be per.
 * Otherwise the card would read «600 Kč договорная».
 */
export function typedPrice(row: Draft, price: string, unit: PriceUnit): Draft {
  return price !== '' && row.unit === 'negotiable'
    ? { ...row, price, unit }
    : { ...row, price };
}
