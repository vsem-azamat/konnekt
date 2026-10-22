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
  /** The price came from the helper's own profile, and the label says so. */
  suggested: boolean;
}

/**
 * A fresh answer to a request, its price already the one the helper's profile
 * asks for this kind of work (`suggested_price`). A price left to agree has no
 * number to start from.
 */
export function openDraft(requestId: number, suggested: Price | null | undefined): Draft {
  if (suggested?.amount == null) {
    return { requestId, message: '', price: '', unit: 'hour', suggested: false };
  }
  return {
    requestId,
    message: '',
    price: String(suggested.amount),
    unit: suggested.unit,
    suggested: true,
  };
}

/**
 * A quick start pressed into the message: the message itself when it is
 * empty, its next sentence otherwise. Pressed twice, it is there once.
 */
export function withStarter(message: string, starter: string): string {
  const typed = message.trimEnd();
  if (!typed) return starter;
  if (typed.includes(starter)) return typed;
  return /[.!?…]$/.test(typed) ? `${typed} ${starter}` : `${typed}. ${starter}`;
}
