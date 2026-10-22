import type { FeedFacetsOut } from './generated/types.gen';
import type { FeedRequest } from './types';

/**
 * The chips over «Входящие», one chosen at a time.
 *
 * One, because the numbers on them are counted over the whole feed: with two
 * chosen, every number beside them would be a count of something not shown.
 */
export type FeedChip = { count: number } & (
  | { kind: 'mine' }
  | { kind: 'all' }
  | { kind: 'shelf'; id: number; name: string }
  | { kind: 'online' }
  | { kind: 'city'; name: string }
  | { kind: 'budget'; amount: number }
);

export function chipKey(chip: FeedChip): string {
  switch (chip.kind) {
    case 'shelf':
      return `shelf:${chip.id}`;
    case 'city':
      return `city:${chip.name}`;
    case 'budget':
      return `budget:${chip.amount}`;
    default:
      return chip.kind;
  }
}

/**
 * In the mockup's order. One that would leave the list empty is not offered,
 * except the one already chosen: its requests can go while it is on, and a
 * row without it would hide the filter in force and the way out of it.
 */
export function feedChips(facets: FeedFacetsOut, chosen?: FeedChip | null): FeedChip[] {
  const chips: FeedChip[] = [
    { kind: 'mine', count: facets.mine },
    { kind: 'all', count: facets.all },
    ...facets.subjects.map(
      (shelf): FeedChip => ({
        kind: 'shelf',
        id: shelf.id,
        name: shelf.name,
        count: shelf.count,
      }),
    ),
    { kind: 'online', count: facets.formats.online },
    ...facets.cities.map(
      (city): FeedChip => ({ kind: 'city', name: city.name, count: city.count }),
    ),
    ...facets.budget_upto.map(
      (step): FeedChip => ({ kind: 'budget', amount: step.amount, count: step.count }),
    ),
  ];
  const kept = chosen ? chipKey(chosen) : null;
  const offered = chips.filter(
    (chip) => chip.kind === 'all' || chip.count > 0 || chipKey(chip) === kept,
  );
  if (chosen && !offered.some((chip) => chipKey(chip) === kept)) {
    offered.push({ ...chosen, count: 0 });
  }
  return offered;
}

/**
 * What the helper came for first; everything, when nothing of theirs waits.
 *
 * `waiting` leaves out what they answered: «Мои услуги» with every card
 * already answered is nothing to open on.
 */
export function defaultChip(waiting: number): FeedChip {
  return waiting > 0 ? { kind: 'mine', count: waiting } : { kind: 'all', count: 0 };
}

export type FeedQuery = {
  // Answered ones stay in, marked «Отклик отправлен»: it is what a helper
  // looks for after answering. The server puts them after the rest.
  with_responded: true;
  mine?: true;
  subject_id?: number;
  work_format?: 'online';
  city?: string;
  budget_upto?: number;
};

export function feedQuery(chip: FeedChip): FeedQuery {
  const query: FeedQuery = { with_responded: true };
  switch (chip.kind) {
    case 'mine':
      return { ...query, mine: true };
    case 'shelf':
      return { ...query, subject_id: chip.id };
    case 'online':
      return { ...query, work_format: 'online' };
    case 'city':
      return { ...query, city: chip.name };
    case 'budget':
      return { ...query, budget_upto: chip.amount };
    default:
      return query;
  }
}

export interface FeedSection {
  /** «По твоим услугам» or «Остальные»; null where a heading would say nothing. */
  heading: 'mine' | 'others' | null;
  rows: FeedRequest[];
}

/**
 * «По твоим услугам», then «Остальные», each with the answered last.
 *
 * The server ranks every unanswered request above every answered one; split
 * by services alone, an answered card would sit over new requests in
 * «Остальные». Under «Мои услуги» every row is the helper's own, and with
 * only one kind on the list a heading over it repeats the chip.
 */
export function feedSections(rows: FeedRequest[], chip: FeedChip): FeedSection[] {
  if (rows.length === 0) return [];
  const ordered = [
    ...rows.filter((row) => !row.responded),
    ...rows.filter((row) => row.responded),
  ];
  const mine = ordered.filter((row) => row.on_my_services);
  const others = ordered.filter((row) => !row.on_my_services);
  if (chip.kind === 'mine' || mine.length === 0 || others.length === 0) {
    return [{ heading: null, rows: ordered }];
  }
  return [
    { heading: 'mine', rows: mine },
    { heading: 'others', rows: others },
  ];
}
