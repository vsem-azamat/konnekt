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

import type { ResponseCreate } from './types';

export function responseDraft(message: string, price: string): ResponseCreate | null {
  const words = message.trim();
  if (words.length < 3) return null;

  const typed = price.trim();
  if (!typed) return { message: words };

  const amount = Number(/^\d+,\d{1,2}$/.test(typed) ? typed.replace(',', '.') : typed);
  if (!Number.isFinite(amount) || amount < 0) return null;
  return { message: words, price_amount: amount, price_unit: 'hour' };
}
