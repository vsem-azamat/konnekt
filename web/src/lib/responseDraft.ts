/**
 * What a helper has typed into the answer sheet, as the server will take it.
 *
 * Null while it cannot go out: fewer than three characters of message, or a
 * price that is not a number. An empty price field means "did not say", not
 * zero, so it leaves the price out of the payload altogether. A comma before
 * one or two digits is a decimal point, the one a Czech or Ukrainian keypad
 * offers; before three it could be a thousands separator («1,000»), and
 * reading that as one crown is worse than not sending.
 */

import type { Price, PriceUnit, ResponseCreate } from './types';

export function responseDraft(
  message: string,
  price: string,
  unit: PriceUnit = 'hour',
): ResponseCreate | null {
  const words = message.trim();
  if (words.length < 3) return null;

  const typed = price.trim();
  if (!typed) return { message: words };

  const amount = Number(/^\d+,\d{1,2}$/.test(typed) ? typed.replace(',', '.') : typed);
  if (!Number.isFinite(amount) || amount < 0) return null;
  return { message: words, price_amount: amount, price_unit: unit };
}

/** The answer sheet's fields for one request, kept while the sheet is closed. */
export interface Draft {
  requestId: number | null;
  message: string;
  price: string;
  unit: PriceUnit;
  /** The price the helper's profile asks, while the field still says it. */
  suggested: string | null;
}

/** As long as the message field takes. */
export const MESSAGE_MAX = 1000;

/**
 * A fresh answer to a request, its price already the one the helper's profile
 * asks for this kind of work (`suggested_price`). A price marked «договорная»
 * is not offered as a number, even when the profile holds one: it would read
 * as fixed to the author.
 */
export function openDraft(requestId: number, suggested: Price | null | undefined): Draft {
  if (suggested?.amount == null || suggested.unit === 'negotiable') {
    return { requestId, message: '', price: '', unit: 'hour', suggested: null };
  }
  const price = String(suggested.amount);
  return { requestId, message: '', price, unit: suggested.unit, suggested: price };
}

/**
 * A quick start pressed into the message: the message itself when it is
 * empty, its next sentence otherwise, or the next line after a line break.
 * Already there, whatever its case, or too long to fit, it is not added.
 */
export function withStarter(message: string, starter: string): string {
  if (message.toLocaleLowerCase().includes(starter.toLocaleLowerCase())) return message;
  const typed = message.replace(/[ \t]+$/, '');
  let next: string;
  if (!typed.trim()) next = starter;
  else if (typed.endsWith('\n')) next = `${typed}${starter}`;
  else if (/[.!?…]$/.test(typed)) next = `${typed} ${starter}`;
  else next = `${typed.replace(/[,;:]+$/, '')}. ${starter}`;
  return next.length > MESSAGE_MAX ? message : next;
}
