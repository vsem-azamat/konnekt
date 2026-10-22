import type { HelpRequest } from './types';

/**
 * «Открытые» and «Закрытые», as «Заявки» splits a person's own requests.
 *
 * A request whose time ran out is closed for the reader, whatever closed it;
 * the card says which. A draft has not been asked yet and is in neither.
 */
export function buckets(requests: HelpRequest[]): {
  open: HelpRequest[];
  closed: HelpRequest[];
} {
  return {
    open: requests.filter((request) => request.status === 'open'),
    closed: requests.filter(
      (request) => request.status === 'closed' || request.status === 'expired',
    ),
  };
}

const DAY_MS = 24 * 60 * 60 * 1000;

/** Whole days until a request stops being shown: «ещё 26 дней». A started day counts. */
export function daysLeft(expiresAt: string, now: Date = new Date()): number {
  return Math.max(0, Math.ceil((Date.parse(expiresAt) - now.getTime()) / DAY_MS));
}

/** The reader's calendar day an instant falls on, as YYYY-MM-DD for `formatDay`. */
export function localDay(instant: string): string {
  const date = new Date(instant);
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}
